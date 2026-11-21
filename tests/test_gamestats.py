"""Game values (gamestats.py) on a made-up DataCore file, laid out like the game's (no game needed)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dcb_builder import Dcb  # noqa: E402

from sc_explorer import entities, gamestats  # noqa: E402

VEC3 = {"x": "f32", "y": "f32", "z": "f32"}
DAMAGE = {f"Damage{d}": "f32" for d in ("Physical", "Energy", "Distortion", "Thermal", "Biochemical", "Stun")}
STRUCTS = {
    "EntityClassDefinition": {"Components": "[strong]"},
    "Vec3": VEC3,
    "DamageInfo": DAMAGE,
    "Path": {"path": "str"},
    "GeoInner": {"Geometry": "class:Path", "Material": "class:Path"},
    "GeoOuter": {"Geometry": "class:GeoInner"},
    "SGeometryResourceParams": {"Geometry": "class:GeoOuter"},
    "SCItemLocalization": {"Name": "locale"},
    "SCItemManufacturer": {"Code": "str", "Localization": "class:SCItemLocalization"},
    "SItemDefinition": {"Type": "enum", "SubType": "enum", "Size": "i32", "Grade": "i32", "Manufacturer": "ref",
                        "Localization": "class:SCItemLocalization"},
    "SAttachableComponentParams": {"AttachDef": "class:SItemDefinition"},
    "SEntityRigidPhysicsControllerParams": {"Mass": "f32"},
    "SEntityPhysicsControllerParams": {"PhysType": "strong"},
    "SHealthComponentParams": {"Health": "f32"},
    "SProjectileLauncher": {"pelletCount": "i32"},
    "SWeaponActionFireSingleParams": {"fireRate": "i32", "launchParams": "strong"},
    "SWeaponActionFireBurstParams": {"fireRate": "i32", "shotCount": "i32", "launchParams": "strong"},
    "SWeaponActionFireBeamParams": {"damagePerSecond": "class:DamageInfo"},
    "SWeaponSequenceEntryParams": {"delay": "f32", "weaponAction": "strong"},
    "SWeaponActionSequenceParams": {"sequenceEntries": "[class:SWeaponSequenceEntryParams]"},
    "SWeaponRegenConsumerParams": {"maxAmmoLoad": "f32", "maxRegenPerSec": "f32"},
    "SCItemWeaponComponentParams": {"ammoContainerRecord": "ref", "fireActions": "[strong]",
                                    "weaponRegenConsumerParams": "strong"},
    "SAmmoContainerComponentParams": {"maxAmmoCount": "i32", "lowAmmoWarningPercentage": "f32",
                                      "ammoParamsRecord": "ref"},
    "ExplosionParams": {"damage": "class:DamageInfo", "minRadius": "f32", "maxRadius": "f32"},
    "ProjectileDetonationParams": {"explosionParams": "class:ExplosionParams"},
    "BulletProjectileParams": {"damage": "strong", "detonationParams": "strong"},
    "AmmoParams": {"speed": "f32", "lifetime": "f32", "projectileParams": "strong"},
    "SItemPortLoadoutEntryParams": {"itemPortName": "str", "entityClassName": "str", "entityClassReference": "ref",
                                    "loadout": "strong"},
    "SItemPortLoadoutManualParams": {"entries": "[class:SItemPortLoadoutEntryParams]"},
    "SEntityComponentDefaultLoadoutParams": {"loadout": "strong"},
    "VehicleComponentParams": {"vehicleName": "locale", "vehicleCareer": "locale", "vehicleRole": "locale",
                               "crewSize": "i32", "maxBoundingBoxSize": "class:Vec3", "manufacturer": "ref",
                               "vehicleDefinition": "str"},
    "IFCSParams": {"scmSpeed": "f32", "maxSpeed": "f32", "boostSpeedForward": "f32", "boostSpeedBackward": "f32",
                   "maxAngularVelocity": "class:Vec3"},
    "SCItemShieldGeneratorParams": {"MaxShieldHealth": "f32", "MaxShieldRegen": "f32", "DamagedRegenDelay": "f32",
                                    "DownedRegenDelay": "f32"},
    "SQuantumDriveParams": {"driveSpeed": "f32", "spoolUpTime": "f32", "cooldownTime": "f32"},
    "SCItemQuantumDriveParams": {"quantumFuelRequirement": "f32", "params": "class:SQuantumDriveParams"},
    "InventoryContainer": {"interiorDimensions": "class:Vec3"},
    "SCItemInventoryContainerComponentParams": {"containerParams": "ref"},
    "GCS": {"linearSpeed": "f32"},
    "Targeting": {"lockTime": "f32", "lockRangeMax": "f32", "trackingSignalType": "enum"},
    "SCItemMissileParams": {"explosionParams": "class:ExplosionParams", "GCSParams": "class:GCS",
                            "targetingParams": "class:Targeting"},
    "SDamageResistanceEntry": {"Multiplier": "f32", "Threshold": "f32"},
    "DamageResistance": {f"{d}Resistance": "class:SDamageResistanceEntry"
                         for d in ("Physical", "Energy", "Distortion", "Thermal", "Biochemical", "Stun")},
    "DamageResistanceMacro": {"damageResistance": "class:DamageResistance"},
    "SCItemSuitArmorParams": {"damageResistance": "ref"},
    "TemperatureResistance": {"MinResistance": "f32", "MaxResistance": "f32"},
    "SCItemClothingParams": {"TemperatureResistance": "class:TemperatureResistance"},
}
HORNET = "objects/spaceships/ships/anvl/hornet/anvl_hornet.cga"
RIFLE = "objects/fps_weapons/weapons_v7/behr/rifle/behr_rifle.cgf"
HORNET_XML = (b'<Vehicle name="Hornet"><Parts><Part name="Body" mass="70000" damageMax="9000"><Parts>'
              b'<Part name="Wing" mass="3000" damageMax="1500"/></Parts></Part></Parts></Vehicle>')


def _attach(typ, size=0, grade=0, name="", sub="", maker="SCItemManufacturer.BEHR"):
    return {"_type": "SAttachableComponentParams",
            "AttachDef": {"Type": typ, "SubType": sub, "Size": size, "Grade": grade, "Manufacturer": maker,
                          "Localization": {"Name": name}}}


def _geo(path):
    return {"_type": "SGeometryResourceParams", "Geometry": {"Geometry": {"Geometry": {"path": path}}}}


def _loadout(*entries):
    return {"_type": "SEntityComponentDefaultLoadoutParams",
            "loadout": {"_type": "SItemPortLoadoutManualParams",
                        "entries": [{"itemPortName": p, "entityClassName": n,
                                     "loadout": {"_type": "SItemPortLoadoutManualParams",
                                                 "entries": [{"itemPortName": q, "entityClassName": m} for q, m in sub]}
                                     if sub else None}
                                    for p, n, sub in entries]}}


def _single(rate, pellets=1):
    return {"_type": "SWeaponActionFireSingleParams", "fireRate": rate,
            "launchParams": {"_type": "SProjectileLauncher", "pelletCount": pellets}}


def _entity(b, name, *comps):
    b.record(f"EntityClassDefinition.{name}", {"_type": "EntityClassDefinition", "Components": list(comps)})


def _datacore():
    b = Dcb(STRUCTS)
    b.record("SCItemManufacturer.BEHR", {"_type": "SCItemManufacturer", "Code": "BEHR",
                                         "Localization": {"Name": "@manufacturer_NameBEHR"}})
    b.record("SCItemManufacturer.ANVL", {"_type": "SCItemManufacturer", "Code": "ANVL",
                                         "Localization": {"Name": "@LOC_PLACEHOLDER"}})
    # a rifle: 600 shots a minute, 20 damage a shot, a 30-round magazine in its factory loadout
    b.record("AmmoParams.Rifle", {"_type": "AmmoParams", "speed": 900.0, "lifetime": 2.0, "projectileParams": {
        "_type": "BulletProjectileParams", "damage": {"_type": "DamageInfo", "DamagePhysical": 20.0}}})
    _entity(b, "behr_rifle_mag", _attach("WeaponAttachment", sub="Magazine"),
            {"_type": "SAmmoContainerComponentParams", "maxAmmoCount": 30, "ammoParamsRecord": "AmmoParams.Rifle"})
    _entity(b, "behr_rifle", _geo("Data/" + RIFLE), _attach("WeaponPersonal", 2, 1, "@item_NameRifle", sub="Medium"),
            {"_type": "SEntityPhysicsControllerParams",
             "PhysType": {"_type": "SEntityRigidPhysicsControllerParams", "Mass": 3.5}},
            {"_type": "SCItemWeaponComponentParams", "fireActions": [
                _single(600), {"_type": "SWeaponActionFireBurstParams", "fireRate": 900, "shotCount": 3}]},
            _loadout(("magazine_attach", "behr_rifle_mag", None)))
    # a shotgun that names its ammunition itself: 8 pellets of 10, and a blast of 5 around each
    b.record("AmmoParams.Shell", {"_type": "AmmoParams", "speed": 300.0, "lifetime": 0.5, "projectileParams": {
        "_type": "BulletProjectileParams", "damage": {"_type": "DamageInfo", "DamagePhysical": 10.0},
        "detonationParams": {"_type": "ProjectileDetonationParams",
                             "explosionParams": {"damage": {"DamageEnergy": 5.0}, "maxRadius": 1.5}}}})
    _entity(b, "behr_shotgun", _attach("WeaponPersonal", 3),
            {"_type": "SCItemWeaponComponentParams", "ammoContainerRecord": "AmmoParams.Shell",
             "fireActions": [_single(60, 8)]})
    # a ship laser: its shots come in a sequence, the ammunition is its own, a capacitor feeds it
    b.record("AmmoParams.Laser", {"_type": "AmmoParams", "speed": 1800.0, "lifetime": 1.5, "projectileParams": {
        "_type": "BulletProjectileParams", "damage": {"_type": "DamageInfo", "DamageEnergy": 50.0}}})
    _entity(b, "behr_laser_s3", _attach("WeaponGun", 3, 2, sub="Gun"),
            {"_type": "SAmmoContainerComponentParams", "maxAmmoCount": 0, "ammoParamsRecord": "AmmoParams.Laser"},
            {"_type": "SCItemWeaponComponentParams",
             "weaponRegenConsumerParams": {"_type": "SWeaponRegenConsumerParams", "maxAmmoLoad": 40.0,
                                           "maxRegenPerSec": 8.0},
             "fireActions": [{"_type": "SWeaponActionSequenceParams", "sequenceEntries": [
                 {"weaponAction": _single(300)}, {"weaponAction": _single(300)}]}]})
    _entity(b, "behr_beam", _attach("WeaponGun", 2),
            {"_type": "SCItemWeaponComponentParams", "fireActions": [
                {"_type": "SWeaponActionFireBeamParams", "damagePerSecond": {"DamageEnergy": 120.0}}]})
    _entity(b, "tractor", _attach("WeaponGun", 1), {"_type": "SCItemWeaponComponentParams"})       # does no damage
    _entity(b, "turret", _attach("Turret", 4))
    _entity(b, "missile_s2", _attach("Missile", 2),
            {"_type": "SCItemMissileParams", "explosionParams": {"damage": {"DamagePhysical": 1500.0}, "maxRadius": 6.0},
             "GCSParams": {"linearSpeed": 700.0},
             "targetingParams": {"lockTime": 2.5, "lockRangeMax": 4000.0, "trackingSignalType": "Infrared"}})
    _entity(b, "shield_s1", _attach("Shield", 1),
            {"_type": "SCItemShieldGeneratorParams", "MaxShieldHealth": 2000.0, "MaxShieldRegen": 100.0,
             "DamagedRegenDelay": 4.0, "DownedRegenDelay": 9.0})
    _entity(b, "qdrive", _attach("QuantumDrive", 1),
            {"_type": "SCItemQuantumDriveParams", "quantumFuelRequirement": 0.02,
             "params": {"driveSpeed": 200000000.0, "spoolUpTime": 5.0, "cooldownTime": 12.0}})
    _entity(b, "flight_controller", _attach("FlightController"),
            {"_type": "IFCSParams", "scmSpeed": 230.0, "maxSpeed": 1200.0, "boostSpeedForward": 500.0,
             "maxAngularVelocity": {"x": 60.0, "y": 180.0, "z": 45.0}})
    b.record("InventoryContainer.Grid", {"_type": "InventoryContainer",
                                         "interiorDimensions": {"x": 2.5, "y": 5.0, "z": 1.25}})
    _entity(b, "cargo_grid", _attach("CargoGrid"),
            {"_type": "SCItemInventoryContainerComponentParams", "containerParams": "InventoryContainer.Grid"})
    ship = [_geo("Data/" + HORNET), _attach("Vehicle"),
            {"_type": "VehicleComponentParams", "vehicleName": "@vehicle_NameANVL_Hornet",
             "vehicleRole": "@vehicle_focus_fighter", "vehicleCareer": "@vehicle_class_combat", "crewSize": 1,
             "maxBoundingBoxSize": {"x": 21.5, "y": 22.5, "z": 5.5}, "manufacturer": "SCItemManufacturer.ANVL",
             "vehicleDefinition": "Scripts/Entities/Vehicles/Implementations/Xml/ANVL_Hornet.xml"},
            _loadout(("hardpoint_controller", "flight_controller", None),
                     ("hardpoint_shield_left", "shield_s1", None), ("hardpoint_shield_right", "shield_s1", None),
                     ("hardpoint_turret", "turret", [("gun_left", "behr_laser_s3"), ("gun_right", "behr_laser_s3")]),
                     ("hardpoint_nose", "behr_beam", None), ("hardpoint_tractor", "tractor", None),
                     ("missile_1", "missile_s2", None), ("missile_2", "missile_s2", None),
                     ("hardpoint_cargo", "cargo_grid", None), ("hardpoint_qd", "qdrive", None),
                     ("hardpoint_gone", "not_in_the_game", None))]
    _entity(b, "ANVL_Hornet", *ship)
    # the same hull, sold under another name with its own health
    _entity(b, "ANVL_Hornet_Tracker", *ship, {"_type": "SHealthComponentParams", "Health": 12000.0})
    b.record("DamageResistanceMacro.Heavy", {"_type": "DamageResistanceMacro", "damageResistance": {
        "PhysicalResistance": {"Multiplier": 0.6}, "EnergyResistance": {"Multiplier": 0.75},
        "StunResistance": {"Multiplier": 1.0}}})
    _entity(b, "heavy_core", _attach("Char_Armor_Torso", name="@item_NameCore"),
            {"_type": "SCItemSuitArmorParams", "damageResistance": "DamageResistanceMacro.Heavy"},
            {"_type": "SCItemClothingParams", "TemperatureResistance": {"MinResistance": -70.0, "MaxResistance": 100.0}})
    _entity(b, "tshirt", _attach("Char_Clothing_Torso_0", name="@item_NameShirt"))         # nothing to tell
    return b.build()


def _read(path):
    return HORNET_XML if path.lower().endswith("anvl_hornet.xml") else None


@pytest.fixture(scope="module")
def index():
    data = _datacore()
    return gamestats.build(entities.open_index(data, _read), _read)


def _stats(index, record):
    return gamestats.flat(index["records"][record.lower()])


def test_rifle_takes_its_damage_from_the_magazine(index):
    e = index["records"]["behr_rifle"]
    assert (e["kind"], e["name"], e["geo"]) == ("weapon", "item_namerifle", RIFLE)
    s = gamestats.flat(e)
    assert s["fire_mode"] == "single" and s["fire_rate"] == 600 and s["alpha"] == 20 and s["dps"] == 200
    assert s["dmg_physical"] == 20 and "dmg_energy" not in s and "pellets" not in s
    assert s["magazine"] == 30 and s["ammo_speed"] == 900 and s["range"] == 1800
    assert s["other_modes"] == "burst 900 rpm"
    assert (s["type"], s["size"], s["grade"], s["mass"]) == ("WeaponPersonal / Medium", 2, 1, 3.5)
    assert s["manufacturer"] == "@manufacturer_NameBEHR"
    assert [g for g, _ in e["groups"]] == ["general", "weapon"]


def test_pellets_and_blast_count_in_a_shot(index):
    s = _stats(index, "behr_shotgun")
    assert s["pellets"] == 8 and s["alpha"] == 120 and s["dps"] == 120         # 8 × (10 + 5), once a second
    assert s["dmg_physical"] == 10 and s["dmg_energy"] == 5
    assert s["explosion_damage"] == 5 and s["explosion_radius"] == 1.5 and s["range"] == 150
    assert "magazine" not in s


def test_ship_guns(index):
    s = _stats(index, "behr_laser_s3")
    assert index["records"]["behr_laser_s3"]["kind"] == "ship_weapon"
    assert s["fire_rate"] == 300 and s["alpha"] == 50 and s["dps"] == 250 and "other_modes" not in s
    assert s["capacitor"] == 40 and s["capacitor_regen"] == 8
    beam = _stats(index, "behr_beam")
    assert beam["fire_mode"] == "beam" and beam["dps"] == 120 and "fire_rate" not in beam


def test_what_has_no_values_is_left_out(index):
    assert "tractor" not in index["records"] and "tshirt" not in index["records"]
    assert "turret" not in index["records"] and "behr_rifle_mag" not in index["records"]


def test_ship_reads_its_loadout(index):
    e = index["records"]["anvl_hornet"]
    assert e["kind"] == "ship" and e["name"] == "vehicle_nameanvl_hornet"
    assert [g for g, _ in e["groups"]] == ["vehicle", "flight", "loadout"]
    s = gamestats.flat(e)
    assert (s["role"], s["career"], s["crew"]) == ("@vehicle_focus_fighter", "@vehicle_class_combat", 1)
    assert s["manufacturer"] == "ANVL"                                  # no name in the game's texts: its code
    assert (s["length"], s["width"], s["height"]) == (22.5, 21.5, 5.5)
    assert s["hull_hp"] == 10500 and s["mass"] == 73000                 # the parts of the vehicle's XML
    assert (s["scm_speed"], s["max_speed"], s["boost_speed"]) == (230, 1200, 500)
    assert (s["pitch"], s["yaw"], s["roll"]) == (60, 45, 180)
    assert (s["shield_hp"], s["shield_regen"], s["shields"]) == (4000, 200, 2)
    assert s["weapons"] == "2× S3, 1× S2" and s["weapons_dps"] == 620     # the tractor beam is not a gun
    assert s["missiles"] == 2 and s["cargo"] == 8 and s["quantum_speed"] == 200000
    assert _stats(index, "ANVL_Hornet_Tracker")["hull_hp"] == 12000     # its own health comes first


def test_components_and_armour(index):
    assert _stats(index, "shield_s1")["regen_delay_down"] == 9
    q = _stats(index, "qdrive")
    assert (q["quantum_speed"], q["spool_time"], q["cooldown"]) == (200000, 5, 12)
    m = _stats(index, "missile_s2")
    assert (m["explosion_damage"], m["speed"], m["lock_time"], m["tracking"]) == (1500, 700, 2.5, "Infrared")
    a = _stats(index, "heavy_core")
    assert (a["res_physical"], a["res_energy"]) == (40, 25) and "res_stun" not in a
    assert (a["temp_min"], a["temp_max"]) == (-70, 100)


def test_records_that_share_a_model(index):
    got = gamestats.for_path(index, "Objects/Spaceships/Ships/ANVL/Hornet/ANVL_Hornet.cga")
    assert [e["record"] for e in got] == ["ANVL_Hornet", "ANVL_Hornet_Tracker"]
    assert gamestats.for_path(index, "objects/nothing.cgf") == [] and gamestats.for_path(None, HORNET) == []
    assert [e["record"] for e in gamestats.of_kind(index, "ship_weapon")] == ["behr_beam", "behr_laser_s3"]


def test_coverage_tells_what_is_never_found(index):
    cov = gamestats.coverage(index)
    assert cov["weapon"] == {"records": 2, "stats": cov["weapon"]["stats"]} and cov["weapon"]["stats"]["dps"] == 2
    assert cov["ship"]["records"] == 2
    gone = gamestats.missing(index)
    assert {"boost_speed_back", "cooling_rate", "thrust"} <= set(gone) and not {"dps", "hull_hp", "cargo"} & set(gone)
    assert set(gamestats.UNITS) >= {k for e in index["records"].values() for k in gamestats.flat(e)}


def test_raw_values_follow_the_records_they_name():
    data = _datacore()
    dc = entities.open_index(data).dc
    assert gamestats.find_record(dc, "nothing") is None
    got = gamestats.raw(dc, gamestats.find_record(dc, "BEHR_Rifle_Mag"))
    ammo = next(c for c in got["Components"] if c["_type"] == "SAmmoContainerComponentParams")
    assert ammo["maxAmmoCount"] == 30 and ammo["ammoParamsRecord"]["_ref"] == "AmmoParams.Rifle"
    assert ammo["ammoParamsRecord"]["projectileParams"]["damage"]["DamagePhysical"] == 20.0
    ship = gamestats.raw(dc, gamestats.find_record(dc, "anvl_hornet"))
    veh = next(c for c in ship["Components"] if c["_type"] == "VehicleComponentParams")
    assert veh["manufacturer"]["Code"] == "ANVL" and veh["crewSize"] == 1
    assert "IFCSParams" in gamestats.schema(dc, "scmspeed") and "Vec3" in gamestats.schema(dc, "vec3")


def test_entities_index_shares_the_opened_file():
    data = _datacore()
    idx = entities.open_index(data, _read)
    out = entities.build(data, _read, idx=idx)
    assert out["ammo"][RIFLE]["max"] == 30 and out["names"][RIFLE] == ["item_namerifle"]
    assert out == entities.build(data, _read)
