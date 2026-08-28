"""Validate and render the generated enclosure STLs with Blender."""

from pathlib import Path
import json
import math

import bpy
import bmesh
from mathutils import Vector


ROOT = Path(__file__).resolve().parent


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def import_stl(path):
    before = set(bpy.data.objects)
    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=str(path))
    else:
        bpy.ops.import_mesh.stl(filepath=str(path))
    created = list(set(bpy.data.objects) - before)
    if len(created) != 1:
        raise RuntimeError(f"Expected one object from {path}, got {len(created)}")
    obj = created[0]
    obj.name = path.stem
    return obj


def validate(obj):
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    non_manifold = [edge for edge in bm.edges if not edge.is_manifold]
    result = {
        "dimensions_mm": [round(v, 3) for v in obj.dimensions],
        "vertices": len(bm.verts),
        "edges": len(bm.edges),
        "faces": len(bm.faces),
        "non_manifold_edges": len(non_manifold),
        "boundary_edges": sum(1 for edge in bm.edges if edge.is_boundary),
        "volume_mm3": round(abs(bm.calc_volume(signed=True)), 3),
    }
    if non_manifold:
        result["non_manifold_midpoints_mm"] = [
            [round(v, 3) for v in ((edge.verts[0].co + edge.verts[1].co) / 2)]
            for edge in non_manifold[:32]
        ]
    bm.free()
    return result


def look_at(obj, target=(0, 0, 2)):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def material(name, rgba, metallic=0.0, roughness=0.45):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = rgba
    mat.metallic = metallic
    mat.roughness = roughness
    return mat


def render_scene(bottom, lid):
    bottom.location = (-14, 0, 0)
    lid.location = (14, 0, 0)
    bottom.data.materials.append(material("matte_black", (0.10, 0.11, 0.14, 1)))
    lid.data.materials.append(material("smoke", (0.28, 0.31, 0.38, 1), roughness=0.32))

    bpy.ops.mesh.primitive_plane_add(size=100, location=(0, 0, -0.05))
    floor = bpy.context.object
    floor.data.materials.append(material("floor", (0.42, 0.45, 0.52, 1), metallic=0.1, roughness=0.7))

    bpy.ops.object.light_add(type="AREA", location=(0, -18, 32))
    bpy.context.object.data.energy = 2600
    bpy.context.object.data.shape = "DISK"
    bpy.context.object.data.size = 18
    bpy.ops.object.light_add(type="AREA", location=(30, 8, 18))
    bpy.context.object.data.energy = 1800
    bpy.context.object.data.size = 12

    bpy.ops.object.camera_add(location=(67, -76, 56))
    camera = bpy.context.object
    look_at(camera)
    camera.data.lens = 53
    bpy.context.scene.camera = camera

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1100
    scene.render.resolution_y = 700
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.color = (0.16, 0.18, 0.22)
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = 1.0
    scene.render.filepath = str(ROOT / "case_parts_preview.png")
    bpy.ops.render.render(write_still=True)

    # A second angle exposes the cap cavity and skirt so wall continuity can
    # be checked visually as well as topologically.
    bottom.hide_render = True
    lid.rotation_euler[0] = math.radians(180)
    lid.location.z = 3.6
    scene.render.filepath = str(ROOT / "case_lid_underside_preview.png")
    bpy.ops.render.render(write_still=True)


clear_scene()
bottom = import_stl(ROOT / "ghosthands_xiao_rp2040_bottom.stl")
lid = import_stl(ROOT / "ghosthands_xiao_rp2040_lid.stl")
plate = import_stl(ROOT / "ghosthands_xiao_rp2040_case_print_plate.stl")
report = {"bottom": validate(bottom), "lid": validate(lid), "print_plate": validate(plate)}
plate.hide_render = True
(ROOT / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
render_scene(bottom, lid)
print(json.dumps(report, indent=2))
