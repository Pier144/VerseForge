"""meshoptimizer encoders (EXT_meshopt_compression, decoded in the browser by three.js's MeshoptDecoder), in numpy.

- vertex codec, version 0 (the one the meshoptimizer 0.18 decoder shipped with three r160 reads): per block of up to
  256 vertices, each byte of the vertex is delta-coded against the previous vertex, zigzagged and bit-packed in groups
  of 16 (0, 2, 4 or 8 bits, with outliers stored as whole bytes).
- index sequence codec (mode INDICES): zigzag delta against the previous index as a varint. The reference encoder
  also switches between two baselines; using only the first one is a valid stream, a little larger."""
import numpy as np

VERTEX_HEADER = 0xA0
SEQUENCE_HEADER = 0xD1
_GROUP = 16
_TAIL = 32


def _encode_blocks(z):
    """z: (blocks, vertices per block (multiple of 16), vertex size) zigzagged deltas -> encoded bytes of the blocks."""
    nb, length, size = z.shape
    ng = length // _GROUP
    rows = nb * size
    g = np.ascontiguousarray(z.transpose(0, 2, 1)).reshape(rows, ng, _GROUP)
    zero = g.max(2) == 0
    s2 = 4 + (g >= 3).sum(2, dtype=np.uint8)
    s4 = 8 + (g >= 15).sum(2, dtype=np.uint8)
    mode = np.full((rows, ng), 3, np.uint8)
    nbytes = np.full((rows, ng), 16, np.int64)
    mode[zero], nbytes[zero] = 0, 0
    m = s2 < nbytes
    mode[m], nbytes[m] = 1, s2[m]
    m = s4 < nbytes
    mode[m], nbytes[m] = 2, s4[m]
    hb = (ng + 3) // 4
    mp = np.zeros((rows, hb * 4), np.uint8)
    mp[:, :ng] = mode
    mp = mp.reshape(rows, hb, 4)
    header = mp[..., 0] | (mp[..., 1] << 2) | (mp[..., 2] << 4) | (mp[..., 3] << 6)
    width = 24
    items = np.zeros((rows, 1 + ng, width), np.uint8)
    items[:, 0, :hb] = header
    pay = items[:, 1:]
    sel = mode == 3
    pay[sel, :16] = g[sel]
    for code, bits, sentinel in ((1, 2, 3), (2, 4, 15)):
        sel = mode == code
        if not sel.any():
            continue
        v = g[sel]
        e = np.minimum(v, sentinel)
        per = 8 // bits
        packed = np.zeros((len(v), _GROUP // per), np.uint8)
        for k in range(per):
            packed |= e[:, k::per] << (bits * (per - 1 - k))
        fixed = _GROUP // per
        block = np.zeros((len(v), width), np.uint8)
        block[:, :fixed] = packed
        big = v >= sentinel                                  # outliers follow as whole bytes, in their order
        r, c = np.nonzero(big)
        block[r, fixed - 1 + np.cumsum(big, 1, dtype=np.uint8)[r, c]] = v[r, c]
        pay[sel] = block
    lens = np.concatenate([np.full((rows, 1), hb, np.int64), nbytes], 1)
    return items[np.arange(width) < lens[..., None]], lens.sum(1).reshape(nb, size).sum(1)


def _block_size(stride):
    return min(256, (8192 // stride) & ~(_GROUP - 1))


def _zigzag_deltas(v):
    prev = np.empty_like(v)
    if len(v):
        prev[0] = v[0]                              # the first vertex is its own reference
        prev[1:] = v[:-1]
    d = v - prev                                    # uint8 wraps
    return (d << 1) ^ ((d >> 7) * np.uint8(0xFF))


def _blocks(z, pool):
    """Encode equal-length blocks, split across the pool -> (bytes array, length of each block)."""
    if not len(z):
        return np.zeros(0, np.uint8), np.zeros(0, np.int64)
    step = 1024
    chunks = [z[i:i + step] for i in range(0, len(z), step)]
    res = list(pool.map(_encode_blocks, chunks)) if pool and len(chunks) > 1 else [_encode_blocks(c) for c in chunks]
    return np.concatenate([r[0] for r in res]), np.concatenate([r[1] for r in res])


def encode_vertex_buffers(items, pool=None):
    """items: [(bytes-like of count * stride bytes, stride)] (stride a multiple of 4, at most 256) -> [encoded bytes].
    All the blocks of one stride are encoded together (one numpy pass instead of one per mesh)."""
    out = [None] * len(items)
    by_stride = {}
    for i, (_, st) in enumerate(items):
        by_stride.setdefault(st, []).append(i)
    for st, ids in by_stride.items():
        block = _block_size(st)
        verts = {i: np.frombuffer(items[i][0], np.uint8).reshape(-1, st) for i in ids}
        full, part = [], {}
        for i in ids:
            z = _zigzag_deltas(verts[i])
            nf = len(z) // block
            full.append(z[:nf * block])
            rest = len(z) - nf * block
            if rest:
                pad = -rest % _GROUP
                t = np.concatenate([z[nf * block:], np.zeros((pad, st), np.uint8)]) if pad else z[nf * block:]
                part.setdefault(rest + pad, []).append((i, t))
        stream, blen = _blocks(np.concatenate(full).reshape(-1, block, st), pool)
        ends = np.concatenate([[0], np.cumsum(blen)])
        nblocks = np.concatenate([[0], np.cumsum([len(f) // block for f in full])])
        body = {i: [stream[ends[nblocks[k]]:ends[nblocks[k + 1]]].tobytes()] for k, i in enumerate(ids)}
        for length, members in part.items():
            pstream, plen = _blocks(np.stack([t for _, t in members]), pool)
            pend = np.concatenate([[0], np.cumsum(plen)])
            for k, (i, _) in enumerate(members):
                body[i].append(pstream[pend[k]:pend[k + 1]].tobytes())
        for i in ids:
            v = verts[i]
            first = v[0].tobytes() if len(v) else bytes(st)
            out[i] = b"".join([bytes([VERTEX_HEADER]), *body[i], bytes(max(_TAIL, st) - st), first])
    return out


def encode_vertex_buffer(data, stride):
    return encode_vertex_buffers([(data, stride)])[0]


def _varints(d):
    """int32 deltas -> (varint bytes of zigzag(d) << 1, byte count of each)."""
    val = (((d << 1) ^ (d >> 31)).view(np.uint32) << 1)       # zigzag, then low bit 0: baseline 0
    nbytes = np.ones(len(val), np.uint8)
    for k in range(1, 5):
        nbytes += val >= (1 << (7 * k))
    if nbytes.max(initial=1) == 1:                              # the usual case: every delta fits one byte
        return val.astype(np.uint8), nbytes
    ends = np.cumsum(nbytes, dtype=np.int64)
    body = np.empty(int(ends[-1]), np.uint8)
    start = ends - nbytes
    for k in range(5):
        sel = np.nonzero(nbytes > k)[0]
        if not len(sel):
            break
        v = (val[sel] >> (7 * k)) & 127
        body[start[sel] + k] = v | ((nbytes[sel] > k + 1) << 7)
    return body, nbytes


def encode_index_sequence(indices):
    """indices: 1-D integer array (values below 2^30) -> mode INDICES stream."""
    return encode_index_sequences([indices])[0]


def encode_index_sequences(arrays):
    """Several index streams at once -> [encoded bytes] (same result as encode_index_sequence on each)."""
    if not arrays:
        return []
    counts = [len(a) for a in arrays]
    joined = np.concatenate([np.asarray(a).astype(np.int32, copy=False) for a in arrays])
    d = np.empty(len(joined), np.int32)
    if len(joined):
        d[0] = joined[0]
        np.subtract(joined[1:], joined[:-1], out=d[1:])
    starts = np.cumsum([0] + counts[:-1])
    for st, c in zip(starts, counts):
        if c:
            d[st] = joined[st]                                   # each stream starts from 0
    body, nbytes = _varints(d)
    ends = np.concatenate([[0], np.cumsum(nbytes, dtype=np.int64)])
    bounds = ends[np.concatenate([[0], np.cumsum(counts)])]
    return [bytes([SEQUENCE_HEADER]) + body[bounds[k]:bounds[k + 1]].tobytes() + bytes(4) for k in range(len(arrays))]
