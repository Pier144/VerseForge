"""The catalogue's ships, vehicles and names, on a made-up archive (no game needed)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import catalog  # noqa: E402

SHIPS = "Data\\Objects\\Spaceships\\Ships\\"
VEH = "Data\\Objects\\Vehicles\\"


class _Archive:
    """Just enough of a P4kArchive for catalog.build / game_names."""

    def __init__(self, files):
        self.files = files
        self.names = list(files)
        self.usize = [len(v) for v in files.values()]

    def read(self, name):
        return self.files[name]


def _archive():
    ini = "\n".join([
        "vehicle_NameAEGS_Redeemer=Aegis Redeemer", "vehicle_NameMISC_Freelancer=MISC Freelancer",
        "vehicle_NameDRAK_Cutlass_Black=Drake Cutlass Black", "vehicle_NameRSI_Phoenix=RSI Constellation Phoenix",
        "vehicle_NameTMBL_Nova=Tumbril Nova", "vehicle_NameARGO_CSV=Argo CSV-SM\\n",
        "item_NameBomb=Stormburst Bomb", "item_NameLivery=Eclipse Ambush Camo Livery", "item_NameSeat=TRGT. STATUS",
        "item_NameAccess=Access", "item_NameOrePod=Greycat ROC Ore Pod", "item_NameTacit=Tacit Suppressor1",
        "item_NameQuell=Quell Suppressor1", "item_NameTest=<= PLACEHOLDER =>", "item_NameRifle=P4-AR Rifle"])
    # the strings of DataCore in an order that makes the old guess wrong: the bomb's name sits just before the
    # Redeemer's hull, a livery before a seat access, another silencer's name before this one's file
    dcb = (b"@item_NameBomb\x00objects/spaceships/ships/aegs/redeemer/exterior/aegs_redeemer.cga\x00"
           b"@item_NameLivery\x00objects/vehicles/grin/roc/grin_roc_cargo_seataccess.cga\x00"
           b"@item_NameQuell\x00objects/fps_weapons/attachments/suppressors/slnc_s01_arma_01.cgf\x00"
           b"@item_NameRifle\x00objects/fps_weapons/weapons_v7/behr/rifle/brfl_fps_behr_p4ar.cgf\x00")
    files = {"Data\\Localization\\english\\global.ini": ini.encode(), "Data\\Game.dcb": dcb}
    for f in ("AEGS\\Redeemer\\Exterior\\AEGS_Redeemer.cga", "AEGS\\Redeemer\\Exterior\\AEGS_Redeemer_Ramp.cga",
              "MISC\\Freelancer_v2\\MISC_Freelancer.cga", "MISC\\Freelancer_v2\\MISC_Freelancer_Seat.cga",
              "DRAK\\Cutlass\\DRAK_Cutlass_Black.cga", "RSI\\Constellation\\RSI_Constellation_Phoenix.cga",
              "RSI\\Constellation\\RSI_Constellation.cga",
              "RSI\\Constellation\\rsi_constellation_gs_phoenix.cga", "AEGS\\Javelin\\AEGS_Javelin.cga",
              "AEGS\\Javelin\\AEGS_Javelin_Turret.cga"):
        files[SHIPS + f] = b"x" * 10
    for f in ("TMBL\\Nova\\TMBL_Nova.cga", "TMBL\\Nova\\TMBL_Nova_Pilot_Seat.cga", "GRIN\\ROC\\GRIN_ROC_Cargo.cga",
              "GRIN\\ROC\\GRIN_ROC_Cargo_SeatAccess.cga", "GRIN\\ROC\\GRIN_ROC_Access.cga", "ARGO\\argo_csv\\argo_csv.cga",
              "GRIN\\ROC\\grin_roc_unnamed.cga"):
        files[VEH + f] = b"x" * 10
    files["Data\\Objects\\fps_weapons\\attachments\\suppressors\\slnc_s01_arma_01.cgf"] = b"x"
    files["Data\\Objects\\fps_weapons\\weapons_v7\\behr\\rifle\\brfl_fps_behr_p4ar.cgf"] = b"x"
    return _Archive(files)


def _index():
    """What entities.build() answers for the archive above."""
    s, v = "objects/spaceships/ships/", "objects/vehicles/"
    veh = lambda name, records=1, tree=1: {"name": name, "records": records, "tree": [0] * tree}   # noqa: E731
    return {
        "vehicles": {
            s + "aegs/redeemer/exterior/aegs_redeemer.cga": veh("vehicle_nameaegs_redeemer"),
            s + "misc/freelancer_v2/misc_freelancer.cga": veh("vehicle_namemisc_freelancer"),
            s + "drak/cutlass/drak_cutlass_black.cga": veh("vehicle_namedrak_cutlass_black"),
            s + "rsi/constellation/rsi_constellation_phoenix.cga": veh("vehicle_namersi_phoenix", records=1, tree=9),
            s + "rsi/constellation/rsi_constellation_gs_phoenix.cga": veh("vehicle_namersi_phoenix", records=6, tree=5),
            v + "tmbl/nova/tmbl_nova.cga": veh("vehicle_nametmbl_nova"),
            v + "argo/argo_csv/argo_csv.cga": veh("vehicle_nameargo_csv"),
        },
        "names": {
            s + "aegs/redeemer/exterior/aegs_redeemer.cga": [],
            v + "tmbl/nova/tmbl_nova_pilot_seat.cga": ["item_nameseat"],
            v + "grin/roc/grin_roc_cargo.cga": ["item_nameorepod"],
            v + "grin/roc/grin_roc_cargo_seataccess.cga": [],
            v + "grin/roc/grin_roc_access.cga": ["item_nameaccess"],
            v + "grin/roc/grin_roc_unnamed.cga": ["item_nametest"],
            "objects/fps_weapons/attachments/suppressors/slnc_s01_arma_01.cgf": ["item_nametacit", "item_namequell"],
        },
    }


def _build():
    arch, index = _archive(), _index()
    items = catalog.build(arch, catalog.game_names(arch, "english", index),
                          {p: (v["records"], len(v["tree"])) for p, v in index["vehicles"].items()})
    return items, {it.path.rsplit("/", 1)[-1]: it for it in items}


def test_guessed_names_alone_are_wrong_here():
    """The case the entity names are for: without them the Redeemer is a bomb."""
    arch = _archive()
    by = {it.path.rsplit("/", 1)[-1]: it for it in catalog.build(arch, catalog.game_names(arch))}
    assert by["AEGS_Redeemer.cga"].name == "Stormburst Bomb"


def test_ships_come_from_the_vehicle_definitions():
    items, by = _build()
    ships = [it.name for it in catalog.search(items, "", "ships")[0]]
    # whatever the file and its folder are called, by name; the Javelin has no definition and keeps the folder rule
    assert ships == ["Constellation Phoenix", "Cutlass Black", "Freelancer", "Redeemer", "Javelin"]
    red = by["AEGS_Redeemer.cga"]
    assert red.whole and red.main and red.kind == "hull" and red.manu == "Aegis Dynamics"
    assert catalog.subtitle(red) == "Aegis Dynamics"            # a ship is not called a "hull"
    assert not by["AEGS_Redeemer_Ramp.cga"].main and not by["MISC_Freelancer_Seat.cga"].main
    assert by["AEGS_Javelin.cga"].main and not by["AEGS_Javelin.cga"].whole


def test_search_finds_the_ship_by_its_full_name_and_first():
    items, by = _build()
    assert catalog.search(items, "freelancer")[0][0] is by["MISC_Freelancer.cga"]
    assert catalog.search(items, "misc freelancer", "ships")[0] == [by["MISC_Freelancer.cga"]]
    assert catalog.search(items, "drake cutlass")[0] == [by["DRAK_Cutlass_Black.cga"]]


def test_two_files_of_one_ship_the_one_the_game_uses_more_stays():
    items, by = _build()
    assert by["rsi_constellation_gs_phoenix.cga"].whole
    old = by["RSI_Constellation_Phoenix.cga"]
    assert not old.whole and not old.main
    # and the folder's old hull, which the game does not fly, is not promoted in its place
    assert not by["RSI_Constellation.cga"].main


def test_vehicles_come_before_their_pieces():
    items, by = _build()
    found = catalog.search(items, "", "vehicles")[0]
    assert [it.name for it in found[:2]] == ["CSV-SM", "Nova"]          # the game's "\n" at the end is dropped
    assert all(it.whole for it in found[:2]) and not any(it.whole for it in found[2:])
    assert catalog.subtitle(by["TMBL_Nova.cga"]) == "Tumbril"


def test_pieces_keep_a_name_only_when_it_is_theirs():
    _, by = _build()
    assert by["GRIN_ROC_Cargo.cga"].name == "Greycat ROC Ore Pod"            # the entity's own name
    assert by["GRIN_ROC_Cargo_SeatAccess.cga"].name == "Roc Cargo Seataccess"  # entity without a name: no guess
    assert by["TMBL_Nova_Pilot_Seat.cga"].name == "Pilot Seat"               # "TRGT. STATUS" says nothing
    assert by["GRIN_ROC_Access.cga"].name == "Roc Access"                    # one word
    assert by["grin_roc_unnamed.cga"].name == "Roc Unnamed"                  # a placeholder text
    assert not by["GRIN_ROC_Cargo_SeatAccess.cga"].game_name


def test_other_items_take_the_entity_name_and_keep_the_guess_without_one():
    _, by = _build()
    assert by["slnc_s01_arma_01.cgf"].name == "Tacit Suppressor1"            # the guess said "Quell"
    assert by["brfl_fps_behr_p4ar.cgf"].name == "P4-AR Rifle"                # no entity in the index: guess kept
