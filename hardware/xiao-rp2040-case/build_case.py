"""Generate a compact CC0 enclosure for the Seeed Studio XIAO RP2040.

Run with Blender 4.x:
    blender --background --python build_case.py

The case is an original clean-room mechanical design based only on Seeed's
published 21.0 x 17.8 mm board envelope and official reference render.
"""

from pathlib import Path
import bpy
import math


OUT = Path(__file__).resolve().parent


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def rounded_box(name, size, location, radius=0.0):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if radius:
        bevel = obj.modifiers.new("edge_round", "BEVEL")
        bevel.width = radius
        bevel.segments = 4
        bevel.limit_method = "ANGLE"
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=bevel.name)
    return obj


def rounded_prism(name, size, location, radius, corner_segments=10):
    """Create a rounded XY prism with sharp, boolean-stable Z edges."""
    width, length, height = size
    half_w, half_l = width / 2, length / 2
    corners = (
        (half_w - radius, half_l - radius, 0),
        (-half_w + radius, half_l - radius, 90),
        (-half_w + radius, -half_l + radius, 180),
        (half_w - radius, -half_l + radius, 270),
    )
    outline = []
    for cx, cy, start_degrees in corners:
        for index in range(corner_segments):
            angle = math.radians(start_degrees + 90 * index / (corner_segments - 1))
            outline.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

    bottom_z, top_z = -height / 2, height / 2
    vertices = [(x, y, bottom_z) for x, y in outline]
    vertices.extend((x, y, top_z) for x, y in outline)
    count = len(outline)
    faces = [list(reversed(range(count))), list(range(count, 2 * count))]
    for index in range(count):
        following = (index + 1) % count
        faces.append((index, following, count + following, count + index))

    mesh = bpy.data.meshes.new(f"{name}_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    return obj


def cylinder(name, radius, depth, location, vertices=64):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices, radius=radius, depth=depth, location=location
    )
    obj = bpy.context.object
    obj.name = name
    return obj


def boolean(target, cutter, operation="DIFFERENCE"):
    bpy.context.view_layer.objects.active = target
    mod = target.modifiers.new(f"{operation.lower()}_{cutter.name}", "BOOLEAN")
    mod.operation = operation
    mod.solver = "EXACT"
    mod.object = cutter
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def export_stl(obj, filename):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    path = str(OUT / filename)
    if hasattr(bpy.ops.wm, "stl_export"):
        bpy.ops.wm.stl_export(filepath=path, export_selected_objects=True)
    else:
        bpy.ops.export_mesh.stl(filepath=path, use_selection=True)
    obj.select_set(False)


def export_print_plate(bottom, lid):
    """Export both disconnected, watertight parts as one print-ready STL."""
    bottom_copy = bottom.copy()
    bottom_copy.data = bottom.data.copy()
    lid_copy = lid.copy()
    lid_copy.data = lid.data.copy()
    bpy.context.collection.objects.link(bottom_copy)
    bpy.context.collection.objects.link(lid_copy)

    # Bake the source objects' original world transforms so the imported STL
    # geometry starts at Z=0 before arranging the plate.
    for obj in (bottom_copy, lid_copy):
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    bottom_copy.location = (-14.0, 0.0, 0.0)
    lid_top_z = max(vertex.co.z for vertex in lid_copy.data.vertices)
    lid_copy.location = (14.0, 0.0, lid_top_z)
    lid_copy.rotation_euler[0] = math.radians(180)

    bpy.ops.object.select_all(action="DESELECT")
    bottom_copy.select_set(True)
    lid_copy.select_set(True)
    path = str(OUT / "ghosthands_xiao_rp2040_case_print_plate.stl")
    if hasattr(bpy.ops.wm, "stl_export"):
        bpy.ops.wm.stl_export(filepath=path, export_selected_objects=True)
    else:
        bpy.ops.export_mesh.stl(filepath=path, use_selection=True)
    bpy.data.objects.remove(bottom_copy, do_unlink=True)
    bpy.data.objects.remove(lid_copy, do_unlink=True)


def build_bottom():
    # Board: 17.8 W x 21.0 L mm. 0.3 mm clearance per side.
    outer_w, outer_l, outer_h = 21.8, 25.0, 6.0
    inner_w, inner_l = 18.4, 21.6
    floor = 1.2

    tray = rounded_box(
        "GhostHands_XIAO_bottom",
        (outer_w, outer_l, outer_h),
        (0, 0, outer_h / 2),
        radius=1.35,
    )
    cavity = rounded_box(
        "board_cavity",
        (inner_w, inner_l, outer_h + 1.0),
        (0, 0, floor + (outer_h + 1.0) / 2),
        radius=0.75,
    )
    boolean(tray, cavity)

    # Open-top USB-C notch. It leaves a 1.15 mm protective lip beneath the
    # receptacle and enough width for a typical moulded USB-C plug.
    usb = rounded_box(
        "usb_c_notch",
        (13.2, 4.0, outer_h - 1.15 + 0.8),
        (0, outer_l / 2, 1.15 + (outer_h - 1.15 + 0.8) / 2),
        radius=0.65,
    )
    boolean(tray, usb)

    # Fingernail reliefs make the board removable without exposing the pins.
    for x in (-outer_w / 2, outer_w / 2):
        relief = cylinder(
            f"finger_relief_{x}",
            radius=2.0,
            depth=3.5,
            location=(x, 0, outer_h - 0.25),
        )
        relief.rotation_euler[1] = math.radians(90)
        bpy.context.view_layer.objects.active = relief
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        boolean(tray, relief)

    # Two shallow, hidden side beads provide positive cap retention. Their
    # 0.15 mm nominal interference is localized so the cap skirts can flex
    # over them without sacrificing the case-wide first-print clearance.
    for x in (-outer_w / 2, outer_w / 2):
        latch = cylinder(
            f"cap_latch_{x}",
            radius=0.45,
            depth=3.0,
            location=(x, -4.5, 4.5),
            vertices=48,
        )
        latch.rotation_euler[0] = math.radians(90)
        bpy.context.view_layer.objects.active = latch
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        boolean(tray, latch, operation="UNION")

    export_stl(tray, "ghosthands_xiao_rp2040_bottom.stl")
    return tray


def build_lid():
    # The cap overlaps the tray by 2.4 mm. A conservative 0.30 mm clearance
    # per side is appropriate for an uncalibrated bureau FDM first print.
    # The 1.2 mm roof and skirt walls reliably resolve with a 0.4 mm nozzle.
    outer_w, outer_l, outer_h = 24.8, 28.0, 3.6
    cavity_w, cavity_l, skirt_depth = 22.4, 25.6, 2.4
    roof, boolean_overcut = 1.2, 0.2

    lid = rounded_box(
        "GhostHands_XIAO_lid",
        (outer_w, outer_l, outer_h),
        (0, 0, outer_h / 2),
        radius=1.55,
    )
    cavity = rounded_prism(
        "tray_cavity",
        (cavity_w, cavity_l, skirt_depth + boolean_overcut),
        (0, 0, (skirt_depth - boolean_overcut) / 2),
        radius=1.15,
    )
    boolean(lid, cavity)

    assert abs(outer_h - skirt_depth - roof) < 1e-9

    # Matching relief pockets capture the tray's side beads after the skirts
    # flex over them. The extra 0.05 mm radius and 1.0 mm length are tolerance
    # for layer lines and bureau-to-bureau dimensional variation.
    for x in (-cavity_w / 2, cavity_w / 2):
        pocket = cylinder(
            f"cap_latch_pocket_{x}",
            radius=0.5,
            depth=4.0,
            location=(x, -4.5, 0.9),
            vertices=48,
        )
        pocket.rotation_euler[0] = math.radians(90)
        bpy.context.view_layer.objects.active = pocket
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        boolean(lid, pocket)

    # Match the tray's USB-C opening through the cap skirt.
    usb = rounded_box(
        "usb_c_cap_notch",
        (13.2, 4.0, skirt_depth + 0.7),
        (0, outer_l / 2, -0.2 + (skirt_depth + 0.7) / 2),
        radius=0.7,
    )
    boolean(lid, usb)

    # BOOT and RESET centres are x=±4.00, y=-8.95 mm in Seeed's official
    # mechanical model. The 3.4 mm openings allow a paperclip or small probe
    # while absorbing normal FDM positional tolerance.
    for x in (-4.0, 4.0):
        access = cylinder(
            f"button_access_{x}",
            radius=1.7,
            depth=2.0,
            location=(x, -8.95, outer_h - 0.45),
        )
        boolean(lid, access)

    # The RGB LED is centred between the rear BOOT and RESET switches in
    # Seeed's official model. This window keeps status light visible.
    light = cylinder(
        "rgb_led_window",
        radius=1.6,
        depth=2.0,
        location=(0, -9.0, outer_h - 0.45),
    )
    boolean(lid, light)

    export_stl(lid, "ghosthands_xiao_rp2040_lid.stl")
    return lid


def save_preview(bottom, lid):
    # Keep both parts separated in the source blend for inspection.
    bottom.location.x = -14.0
    lid.location.x = 14.0
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "ghosthands_xiao_rp2040_case.blend"))


clear_scene()
bottom = build_bottom()
lid = build_lid()
export_print_plate(bottom, lid)
save_preview(bottom, lid)
print("Generated GhostHands XIAO RP2040 enclosure in", OUT)
