
import bpy
import bonsai.tool as tool
from mathutils import Vector
import functools as ft
from bonsai.bim.ifc import IfcStore
import string
import ifcopenshell.api as ifc_api
from ifcopenshell.util.element import get_pset

pset_name = "Pset_Numbering"
_ifc_types = [("IfcElement", "All", "element")]

def load_types(objects):
    """Load the available IFC types from the selected objects."""
    global _ifc_types
    if not objects:
        return _ifc_types, {"IfcElement": 0}
    
    ifc_types = [("IfcElement", "All", "element")]
    seen_types = []
    tag_counts = {"IfcElement": 0}

    for obj in objects:
        element = tool.Ifc.get_entity(obj)
        if not element.is_a("IfcElement"):
            continue
        ifc_type = element.is_a() #Starts with "Ifc", which we can strip by starting from index 3 
       
        if ifc_type not in seen_types:
            seen_types.append(ifc_type) 
            ifc_types.append((ifc_type, ifc_type[3:], ifc_type[3:].lower())) # Store type as (id, name, name_lower)
            tag_counts[ifc_type] = 0

        tag_counts["IfcElement"] += 1
        tag_counts[ifc_type] += 1
            
    ifc_types.sort(key=lambda ifc_type: ifc_type[0] if ifc_type[0] != "IfcElement" else "") #Sort types alphabetically, but keeping IfcElement at index 0
    
    return ifc_types, tag_counts

_select_types = []

def get_select_types(self, context):
    """Return the list of available types for selection."""
    global _select_types

    props = context.scene.ifc_tag_settings
    objects = bpy.context.selected_objects if props.selected_toggle else bpy.context.scene.objects
    ifc_types, tag_counts = load_types(objects)
    select_types = [(id, name + f": {tag_counts[id]}", "") for (id, name, _) in ifc_types]
    if select_types != _select_types:
        _select_types = select_types
    return _select_types

def format_tag(props, element_number=0, type_number=0, level_number=0, type_name="", max_number=100):
    """Return the tag for the given element, type and level number, following the format defined in the UI properties."""
    tag = props.format
    if "{E}" in tag:
        tag = tag.replace("{E}", to_numbering_string(props.initial_element_number + element_number, props.element_numbering, max_number))
    if "{T}" in tag:
        tag = tag.replace("{T}", to_numbering_string(props.initial_type_number + type_number, props.type_numbering, max_number))
    if "{L}" in tag:
        tag = tag.replace("{L}", to_numbering_string(props.initial_level_number + level_number, props.level_numbering, max_number))
    if "[T]" in tag and len(type_name) > 0:
        tag = tag.replace("[T]", type_name[0])
    if "[TF]" in tag:
        tag = tag.replace("[TF]", type_name)
    return tag

def get_type_name(props):
    """Return type name used in preview, based on selected types"""
    global _select_types
    if not props.selected_types:
        #If no types selected, return "Type"
        return "Type"
    #Get the type name of the selected type, excluding 'IfcElement'
    types = props.selected_types
    if 'IfcElement' in types:
        types.remove('IfcElement')
    if len(types)>0:
        return str(list(types)[0][3:])
    #If all selected, return type name of one of the selected types
    all_types = _select_types
    if len(_select_types) > 1:
        return str(_select_types[1][0][3:])
    #If none selected, return "Type"
    return "Type"

def to_number(i):
    """Convert a number to a string."""
    return str(i)

def to_number_ext(i, length=2):
    """Convert a number to a string with leading zeroes."""
    if i < 0:
        return "-" + to_number_ext(-i, length)
    res = str(i)
    while len(res) < length:
        res = "0" + res
    return res

def to_letter(i, upper=False):
    """Convert a number to a letter or sequence of letters."""
    if i == 0:
        return "0"
    if i < 0:
        return "-" + to_letter(-i, upper)

    num2alphadict = dict(zip(range(1, 27), string.ascii_uppercase if upper else string.ascii_lowercase))
    res = ""
    numloops = (i-1) // 26
    
    if numloops > 0:
        res = res + to_letter(numloops, upper)
        
    remainder = i % 26
    if remainder == 0:
        remainder += 26
    return res + num2alphadict[remainder]

# Numbering systems
# Dictionary to map numbering types to functions
numberings = {"number": to_number,
              "number_ext": to_number_ext,
              "lower_letter": to_letter,
              "upper_letter": lambda x: to_letter(x, True)
              }

def to_numbering_string(i, numbering_type, max_number):
    """Convert a number to a string based on the numbering system."""
    if numbering_type == "number_ext":
        # Determine the length based on the maximum number
        length = len(str(max_number))
        return to_number_ext(i, length)
    return numberings[numbering_type](i)

def get_numbering_preview(numbering_type, initial):
    """Get a preview of the numbering string for a given number and type."""
    numbers = [to_numbering_string(i, numbering_type, 10) for i in range(initial, initial + 3)]
    return "{0}, {1}, {2}, ...".format(*numbers)

# Settings (user input fields)
class IFC_TagSettings(bpy.types.PropertyGroup):
    selected_toggle: bpy.props.BoolProperty(
        name="Selected only",
        description="Only tag selected objects",
        default=False
    ) # pyright: ignore[reportInvalidTypeForm]

    selected_types: bpy.props.EnumProperty(
        name="Of type",
        description="Select which types of elements to tag",
        items= get_select_types,
        options={'ENUM_FLAG'}
    )   # pyright: ignore[reportInvalidTypeForm]

    x_direction: bpy.props.EnumProperty(
        name="X",
        description="Select axis direction for tagging elements",
        items=[
            ("1", "+", "Tag elements in positive X direction"),
            ("-1", "-", "Tag elements in negative X direction")
        ],
        default="1",

    )    # pyright: ignore[reportInvalidTypeForm]

    y_direction: bpy.props.EnumProperty(
        name="Y",
        description="Select axis direction for tagging elements",
        items=[
            ("1", "+", "Tag elements in positive Y direction"),
            ("-1", "-", "Tag elements in negative Y direction")
        ],
        default="-1"
    )    # pyright: ignore[reportInvalidTypeForm]

    z_direction: bpy.props.EnumProperty(
        name="Z",
        description="Select axis direction for tagging elements",
        items=[
            ("1", "+", "Tag elements in positive Z direction"),
            ("-1", "-", "Tag elements in negative Z direction")
        ],
        default="1"
    )    # pyright: ignore[reportInvalidTypeForm]

    axis_order: bpy.props.EnumProperty(
        name="Axis order",
        description="Order of axes in tagging elements",
        items=[
            ("XYZ", "X, Y, Z", "Tag elements in X, Y, Z order"),
            ("XZY", "X, Z, Y", "Tag elements in X, Z, Y order"),
            ("YXZ", "Y, X, Z", "Tag elements in Y, X, Z order"),
            ("YZX", "Y, Z, X", "Tag elements in Y, Z, X order"),
            ("ZXY", "Z, X, Y", "Tag elements in Z, X, Y order"),
            ("ZYX", "Z, Y, X", "Tag elements in Z, Y, X order")
        ],
        default="ZYX"
    ) # pyright: ignore[reportInvalidTypeForm]

    location_type: bpy.props.EnumProperty(
        name="Location",
        description="Location to use for sorting elements",
        items=[
            ("CENTER", "Center", "Use object center for sorting"),
            ("BOUNDING_BOX", "Bounding Box", "Use object bounding box for sorting"),
        ],
        default="BOUNDING_BOX"
    ) # pyright: ignore[reportInvalidTypeForm]

    precision: bpy.props.IntVectorProperty(
        name="Precision",
        description="Precision for tagging elements",
        default=(1, 1, 1),
        min=1,
        size=3
    ) # pyright: ignore[reportInvalidTypeForm]

    initial_element_number: bpy.props.IntProperty(
        name="{E}",
        description="Initial number for numbering elements",
        default=1
    ) # pyright: ignore[reportInvalidTypeForm]

    initial_type_number: bpy.props.IntProperty(
        name="{T}",
        description="Initial number for numbering elements within type",
        default=1
    ) # pyright: ignore[reportInvalidTypeForm]

    initial_level_number: bpy.props.IntProperty(
        name="{L}",
        description="Initial number for numbering levels",
        default=0
    ) # pyright: ignore[reportInvalidTypeForm]

    numberings_enum = lambda self, initial : [
            ("number", get_numbering_preview("number", initial), "Use numbers"),
            ("number_ext", get_numbering_preview("number_ext", initial), "Use numbers padded with zeroes to a fixed length based on the number of objects selected"),
            ("lower_letter", get_numbering_preview("lower_letter", initial), "Use lowercase letters, continuing with aa, ab, ..."),
            ("upper_letter", get_numbering_preview("upper_letter", initial), "Use uppercase letters, continuing with AA, AB, ..."),
    ]

    element_numbering: bpy.props.EnumProperty(
        name="{E}",
        description="Select numbering system for element numbering",
        items=lambda self, context: self.numberings_enum(self.initial_element_number)
    )    # pyright: ignore[reportInvalidTypeForm]

    type_numbering: bpy.props.EnumProperty(
        name="{T}",
        description="Select numbering system for numbering within types",
        items=lambda self, context: self.numberings_enum(self.initial_type_number)
    )    # pyright: ignore[reportInvalidTypeForm]

    level_numbering: bpy.props.EnumProperty(
        name="{L}",
        description="Select numbering system for numbering levels",
        items=lambda self, context: self.numberings_enum(self.initial_level_number)
    )    # pyright: ignore[reportInvalidTypeForm]

    format: bpy.props.StringProperty(
        name="Format",
        description="Format string for selected IFC type.\n" \
        "{E}: element number \n" \
        "{T}: number within type, \n" \
        "{L}: number of level\n" \
        "[T]: first letter of type name\n" \
        "[TF]: full type name",
        default="E{E}[T]{T}"
    ) # pyright: ignore[reportInvalidTypeForm]

    save_prop : bpy.props.EnumProperty(
        name="Store tag in",
        items = [("Tag", "Tag", "Store in IFC Tag property"),
                 ("Pset", "Pset", "Store in occurrence property set called " + pset_name)
        ],
        default = "Tag"
    ) # pyright: ignore[reportInvalidTypeForm]

    remove_toggle: bpy.props.BoolProperty(
        name="Remove tags",
        description="Remove existing tags from objects",
        default=True
    ) # pyright: ignore[reportInvalidTypeForm]

    # Draw method (UI layout)
    def draw(self, layout):

        row = layout.row(align=False)
        row.label(text= "Elements to tag:")
        row.prop(self, "selected_toggle")
        layout.prop(self, "selected_types")

        layout.label(text="Tagging order:")
        row = layout.row(align=False)
        row.prop(self, "x_direction", text="X")
        row.prop(self, "y_direction", text="Y")
        row.prop(self, "z_direction", text="Z")
        layout.prop(self, "axis_order")
        layout.prop(self, "location_type")

        layout.label(text="Precision in mm:")
        row = layout.row(align=False)
        row.prop(self, "precision", index=0, text="X")
        row.prop(self, "precision", index=1, text="Y")
        row.prop(self, "precision", index=2, text="Z")

        layout.label(text="Initial values:")
        row = layout.row(align=False)
        row.prop(self, "initial_element_number", text="{E}")
        row.prop(self, "initial_type_number", text="{T}")
        row.prop(self, "initial_level_number", text="{L}")

        row = layout.row(align=False)
        row.prop(self, "element_numbering", text="{E}")
        row.prop(self, "type_numbering", text="{T}")
        row.prop(self, "level_numbering", text="{L}")
   
        row = layout.row(align=False)
        row.prop(self, "format")
        row.label(text="Preview: " + format_tag(self, 0, 0, 0, get_type_name(self), len(bpy.context.selected_objects if self.selected_toggle else bpy.context.scene.objects)))

        layout.prop(self, "save_prop")
        layout.prop(self, "remove_toggle", text="Remove existing tags")
        layout.operator("ifc.assign_tag", icon="TAG", text="Assign tags")

# 2. Operator (button logic)

def get_object_location(obj, props):
    """Get the location of a Blender object."""
    
    mat = obj.matrix_world
    bbox_vectors = [mat @ Vector(b) for b in obj.bound_box]

    if props.location_type == "CENTER":
        return 0.125 * sum(bbox_vectors, Vector())
    
    elif props.location_type == "BOUNDING_BOX":
        bbox_vector = Vector((0, 0, 0))
        # Determine the coordinates based on the direction and axis order
        direction = (int(props.x_direction), int(props.y_direction), int(props.z_direction))
        for i in range(3):
            if direction[i] == 1:
                bbox_vector[i] = min(v[i] for v in bbox_vectors)
            else:
                bbox_vector[i] = max(v[i] for v in bbox_vectors)
        return bbox_vector

def get_object_dimensions(obj):
    """Get the dimensions of a Blender object."""
    # Get the object's bounding box corners in world space
    mat = obj.matrix_world
    coords = [mat @ Vector(corner) for corner in obj.bound_box]

    # Compute min and max coordinates
    min_corner = Vector((min(v[i] for v in coords) for i in range(3)))
    max_corner = Vector((max(v[i] for v in coords) for i in range(3)))

    # Dimensions in global space
    dimensions = max_corner - min_corner
    return dimensions

def cmp_within_precision(a, b, props, use_dir=True):
    """Compare two vectors within a given precision."""
    direction = (int(props.x_direction), int(props.y_direction), int(props.z_direction)) if use_dir else (1, 1, 1)
    for axis in props.axis_order:
        idx = "XYZ".index(axis)
        diff = (a[idx] - b[idx]) * direction[idx]
        if 1000*abs(diff) > props.precision[idx]:
            return 1 if diff > 0 else -1
    return 0

def get_tag(object):
    element = tool.Ifc.get_entity(object)
    tag, prop = None, None    
    if hasattr(element, "Tag"):
        tag = element.Tag
    if pset := get_pset(element, pset_name):
        prop = pset.get("Number")
    return (tag, prop)

def set_tag(element, tag, ifc_file, save_prop=(True, True)):
    count = 0
    if save_prop[0] and hasattr(element, "Tag"):
        count += element.Tag != tag[0]
        element.Tag = tag[0]
    if save_prop[1]:
        if pset := get_pset(element, pset_name):
            count += pset.get("Number") != tag[1]
            pset = ifc_file.by_id(pset["id"])  
        else:
            count += tag[1] is not None
            pset = ifc_api.run("pset.add_pset", ifc_file, product=element, name=pset_name)
        
        if tag[1] is None:
            ifc_api.run("pset.remove_pset", ifc_file, product=element, pset=pset)
        else:    
            ifc_api.run("pset.edit_pset", ifc_file, pset=pset, properties={"Number": tag[1]})
            
    return count

    
def assign_tags(self, context):
    """Assign tags to selected objects based on their IFC type and location."""

    ifc_file = IfcStore.get_file()
    
    props = context.scene.ifc_tag_settings
    tag_count = 0
    remove_count = 0

    if props.remove_toggle:
        #Remove existing tags
        for obj in bpy.context.scene.objects:
            element = tool.Ifc.get_entity(obj)
            if element is not None:
                remove_count += set_tag(element, (None, None), ifc_file, (props.save_prop=="Tag", props.save_prop=="Pset"))
        self.report({'INFO'}, f"Removed {remove_count} existing tags")

    objects = bpy.context.selected_objects if props.selected_toggle else bpy.context.scene.objects
    
    if not objects:
        self.report({'WARNING'}, f"No objects selected or available for tagging, removed {remove_count} existing tags.")
        return {'CANCELLED'}

    elements = []
    for obj in objects: 
        element = tool.Ifc.get_entity(obj)
        if element is not None and any([element.is_a(t) for t in props.selected_types]):
            location = get_object_location(obj, props)
            dimensions = get_object_dimensions(obj)
            elements.append((element, location, dimensions, obj.name))

    if not elements:
        self.report({'WARNING'}, f"No elements selected or available for tagging, removed {remove_count} existing tags.")
        return {'CANCELLED'}
    
    elements.sort(key=ft.cmp_to_key(lambda a, b: cmp_within_precision(a[2], b[2], props, use_dir=False)))
    elements.sort(key=ft.cmp_to_key(lambda a, b: cmp_within_precision(a[1], b[1], props)))

    ifc_types = [t[0] for t in load_types(objects)[0]]
    elements_by_type = [[element[0] for element in elements if element[0].is_a(ifc_type)] 
                        for ifc_type in ifc_types]

    for (element_number, (element, _, _, name)) in enumerate(elements):

        type_index = ifc_types.index(element.is_a())
        type_number = elements_by_type[type_index].index(element)
        type_name = ifc_types[type_index][3:]

        tag = format_tag(props, element_number, type_number, type_name=type_name, max_number=len(objects))

        tag_count += set_tag(element, (tag, tag), ifc_file, (props.save_prop=="Tag", props.save_prop=="Pset"))

    self.report({'INFO'}, f"Assigned tag to {tag_count} objects")

    #Check for duplicate tags
    tags = []
    pset_tags = []
    for obj in bpy.context.scene.objects:
        tag, pset_tag = get_tag(obj)
        element = tool.Ifc.get_entity(obj)
        if tag in tags or pset_tag in pset_tags:
            self.report({'WARNING'}, f"The model contains duplicate tags")
            break
        if tag is not None:
            tags.append(tag)
        if pset_tag is not None:
            pset_tags.append(pset_tag)

    return {'FINISHED'}

class IFC_AssignTag(bpy.types.Operator):
    bl_idname = "ifc.assign_tag"
    bl_label = "Assign tag"
    bl_description = "Assign tag to selected objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        IfcStore.begin_transaction(self)
        old_value = {obj.name: get_tag(obj) for obj in bpy.context.scene.objects}
        result = assign_tags(self, context)
        new_value = {obj.name: get_tag(obj) for obj in bpy.context.scene.objects}
        self.transaction_data = {"old_value": old_value, "new_value": new_value}
        IfcStore.add_transaction_operation(self)
        IfcStore.end_transaction(self)
        return result

    def rollback(self, data):
        rollback_count = 0
        for obj in bpy.context.scene.objects:
            old_tag = data["old_value"][obj.name]
            if old_tag != get_tag(obj):
                set_tag(tool.Ifc.get_entity(obj), old_tag, IfcStore.get_file())
                rollback_count += 1
        print(f"Rollback {rollback_count} tags.")

    def commit(self, data):
        commit_count = 0
        for obj in bpy.context.scene.objects:
            new_tag = data["new_value"][obj.name]
            if new_tag != get_tag(obj):
                set_tag(tool.Ifc.get_entity(obj), new_tag, IfcStore.get_file())
                commit_count += 1
        print(f"Commit {commit_count} tags.")


# 3. UI Panel (where you see it)
class IFCNumberingTool(bpy.types.Panel):
    bl_label = "Number Assignment Tool"
    bl_idname = "VIEW3D_PT_bonsai_ifc_numbering_tool"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Numbering tool'  # This becomes the tab name!

    def draw(self, context):
        layout = self.layout
        props = context.scene.ifc_tag_settings
        props.draw(layout)

# 4. Registration
classes = [IFC_AssignTag, IFC_TagSettings, IFCNumberingTool]


def register():   
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ifc_tag_settings = bpy.props.PointerProperty(type=IFC_TagSettings)
    

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.ifc_tag_settings

register()