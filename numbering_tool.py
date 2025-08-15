
import bpy
import bonsai.tool as tool
from mathutils import Vector
import functools as ft
from bonsai.bim.ifc import IfcStore
import string
import ifcopenshell.api as ifc_api
import ifcopenshell.util.element as ifc_el
import json
import time

pset_numbering_name = "Pset_Numbering"
pset_settings_name = "Pset_NumberingSettings"
ifc_file = IfcStore.get_file()

def load_types(objects):
    """Load the available IFC types from the selected objects."""
    if not objects:
        return [("IfcElement", "All", "element")], {"IfcElement": 0}
    
    ifc_types = [("IfcElement", "All", "element")]
    seen_types = []
    number_counts = {"IfcElement": 0}

    for obj in objects:
        element = tool.Ifc.get_entity(obj)
        if not element.is_a("IfcElement"):
            continue
        ifc_type = element.is_a() #Starts with "Ifc", which we can strip by starting from index 3 
       
        if ifc_type not in seen_types:
            seen_types.append(ifc_type) 
            ifc_types.append((ifc_type, ifc_type[3:], ifc_type[3:].lower())) # Store type as (id, name, name_lower)
            number_counts[ifc_type] = 0

        number_counts["IfcElement"] += 1
        number_counts[ifc_type] += 1
            
    ifc_types.sort(key=lambda ifc_type: ifc_type[0] if ifc_type[0] != "IfcElement" else "") #Sort types alphabetically, but keeping IfcElement at index 0
    
    return ifc_types, number_counts

_possible_types = []
def get_possible_types(self, context):
    """Return the list of available types for selection."""
    global _possible_types
    props = context.scene.ifc_numbering_settings
    objects = bpy.context.selected_objects if props.selected_toggle else bpy.context.scene.objects
    if props.visible_toggle:
        objects = [obj for obj in objects if obj.visible_get()]
    ifc_types, number_counts = load_types(objects)
    possible_types = [(id, name + f": {number_counts[id]}", "") for (id, name, _) in ifc_types]
    if possible_types != _possible_types:
        _possible_types = possible_types
    return _possible_types

def get_storeys(props):
    storeys = []
    for obj in bpy.context.scene.objects:
        element = tool.Ifc.get_entity(obj)
        if element is not None and element.is_a("IfcBuildingStorey"):
            location = get_object_location(obj, props)
            storeys.append((element, location))
    storeys.sort(key=ft.cmp_to_key(lambda a, b: cmp_within_precision(a[1], b[1], props, use_dir=False)))
    storeys = [storey[0] for storey in storeys]  # Extract only the IfcBuildingStorey entities
    return storeys

def format_number(props, number_values = (0, 0, None), max_number_values=(100, 100, 1), type_name=""):
    """Return the formatted number for the given element, type and storey number"""
    format = props.format
    if "{E}" in format:
        format = format.replace("{E}", to_numbering_string(props.initial_element_number + number_values[0], props.element_numbering, max_number_values[0]))
    if "{T}" in format:
        format = format.replace("{T}", to_numbering_string(props.initial_type_number + number_values[1], props.type_numbering, max_number_values[1]))
    if "{S}" in format:
        if number_values[2] is not None:
            format = format.replace("{S}", to_numbering_string(props.initial_storey_number + number_values[2], props.storey_numbering, max_number_values[2]))
        else:
            format = format.replace("{S}", "x")
    if "[T]" in format and len(type_name) > 0:
        format = format.replace("[T]", type_name[0])
    if "[TT]" in format and len(type_name) > 1:
        format = format.replace("[TT]", "".join([c for c in type_name if c.isupper()]))
    if "[TF]" in format:
        format = format.replace("[TF]", type_name)
    return format

def get_type_name(props):
    """Return type name used in preview, based on selected types"""
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
    all_types = _possible_types
    if len(all_types) > 1:
        return str(all_types[1][0][3:])
    #If none selected, return "Type"
    return "Type"

def get_max_numbers(props, type_name):
    """Return number of selected elements used in preview, based on selected types"""
    max_element, max_type, max_storey = 0, 0, 0
    if props.storey_numbering == 'number_ext':
        max_storey = len(get_storeys(props))
    if props.element_numbering == 'number_ext' or props.type_numbering == 'number_ext':
        if not props.selected_types:
            return max_element, max_type, max_storey
        objects = bpy.context.selected_objects if props.selected_toggle else bpy.context.scene.objects
        if props.visible_toggle:
            objects = [obj for obj in objects if obj.visible_get()]
        _, type_counts = load_types(objects)
        if "IfcElement" in props.selected_types:
            max_element = type_counts.get("IfcElement", 0) 
        else:
            max_element = sum(type_counts.get(t, 0) for t in props.selected_types)
        max_type = type_counts.get('Ifc' + type_name, max_element)
    return max_element, max_type, max_storey

def to_number(i):
    """Convert a number to a string."""
    if i < 0:
        return "(" + str(-i) + ")"
    return str(i)

def to_number_ext(i, length=2):
    """Convert a number to a string with leading zeroes."""
    if i < 0:
        return "(" + to_number_ext(-i, length) + ")"
    res = str(i)
    while len(res) < length:
        res = "0" + res
    return res

def to_letter(i, upper=False):
    """Convert a number to a letter or sequence of letters."""
    if i == 0:
        return "0"
    if i < 0:
        return "(" + to_letter(-i, upper) + ")"

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
    if numbering_type == "custom":
        return to_number(i)
    return numberings[numbering_type](i)

def get_numbering_preview(numbering_type, initial):
    """Get a preview of the numbering string for a given number and type."""
    numbers = [to_numbering_string(i, numbering_type, 10) for i in range(initial, initial + 3)]
    return "{0}, {1}, {2}, ...".format(*numbers)

def get_format_preview(props):
    type_name = get_type_name(props)
    return format_number(props, (0, 0, 0), get_max_numbers(props, type_name), type_name)

# Settings (user input fields)
class IFC_NumberingSettings(bpy.types.PropertyGroup):
    settings_name : bpy.props.StringProperty(
        name="Settings name",
        description="Name for saving the current settings",
        default=""
    ) # pyright: ignore[reportInvalidTypeForm]

    def get_saved_settings_items(self, context):
        settings_names = get_settings_names()
        if not settings_names:
            return [("NONE", "No saved settings", "")]
        return [(name, name, "") for name in settings_names]

    saved_settings : bpy.props.EnumProperty(
        name="Load settings",
        description="Select which saved settings to load",
        items=get_saved_settings_items
    ) # pyright: ignore[reportInvalidTypeForm]

    def update_format_preview(self, context):
        self["_format_preview"] = get_format_preview(self)

    selected_toggle: bpy.props.BoolProperty(
        name="Selected only",
        description="Only number selected objects",
        default=False,
        update=update_format_preview
    ) # pyright: ignore[reportInvalidTypeForm]

    visible_toggle: bpy.props.BoolProperty(
        name="Visible only",
        description="Only number visible objects",
        default=False,
        update=update_format_preview
    ) # pyright: ignore[reportInvalidTypeForm]

    selected_types: bpy.props.EnumProperty(
        name="Of type",
        description="Select which types of elements to number",
        items= get_possible_types,
        options={'ENUM_FLAG'},
        update=update_format_preview
    ) # pyright: ignore[reportInvalidTypeForm]

    x_direction: bpy.props.EnumProperty(
        name="X",
        description="Select axis direction for numbering elements",
        items=[
            ("1", "+", "Number elements in positive X direction"),
            ("-1", "-", "Number elements in negative X direction")
        ],
        default="1",
    ) # pyright: ignore[reportInvalidTypeForm]

    y_direction: bpy.props.EnumProperty(
        name="Y",
        description="Select axis direction for numbering elements",
        items=[
            ("1", "+", "Number elements in positive Y direction"),
            ("-1", "-", "Number elements in negative Y direction")
        ],
        default="1"
    ) # pyright: ignore[reportInvalidTypeForm]

    z_direction: bpy.props.EnumProperty(
        name="Z",
        description="Select axis direction for numbering elements",
        items=[
            ("1", "+", "Number elements in positive Z direction"),
            ("-1", "-", "Number elements in negative Z direction")
        ],
        default="1"
    ) # pyright: ignore[reportInvalidTypeForm]

    axis_order: bpy.props.EnumProperty(
        name="Axis order",
        description="Order of axes in numbering elements",
        items=[
            ("XYZ", "X, Y, Z", "Number elements in X, Y, Z order"),
            ("XZY", "X, Z, Y", "Number elements in X, Z, Y order"),
            ("YXZ", "Y, X, Z", "Number elements in Y, X, Z order"),
            ("YZX", "Y, Z, X", "Number elements in Y, Z, X order"),
            ("ZXY", "Z, X, Y", "Number elements in Z, X, Y order"),
            ("ZYX", "Z, Y, X", "Number elements in Z, Y, X order")
        ],
        default="ZYX"
    ) # pyright: ignore[reportInvalidTypeForm]

    location_type: bpy.props.EnumProperty(
        name="Reference location",
        description="Location to use for sorting elements",
        items=[
            ("CENTER", "Center", "Use object center for sorting"),
            ("BOUNDING_BOX", "Bounding Box", "Use object bounding box for sorting"),
        ],
        default="BOUNDING_BOX"
    ) # pyright: ignore[reportInvalidTypeForm]

    precision: bpy.props.IntVectorProperty(
        name="Precision",
        description="Precision for sorting elements in X, Y and Z direction",
        default=(1, 1, 1),
        min=1,
        size=3
    ) # pyright: ignore[reportInvalidTypeForm]

    initial_element_number: bpy.props.IntProperty(
        name="{E}",
        description="Initial number for numbering elements",
        default=1,
        update=update_format_preview
    ) # pyright: ignore[reportInvalidTypeForm]

    initial_type_number: bpy.props.IntProperty(
        name="{T}",
        description="Initial number for numbering elements within type",
        default=1,
        update=update_format_preview
    ) # pyright: ignore[reportInvalidTypeForm]

    initial_storey_number: bpy.props.IntProperty(
        name="{S}",
        description="Initial number for numbering storeys",
        default=0,
        update=update_format_preview
    ) # pyright: ignore[reportInvalidTypeForm]

    numberings_enum = lambda self, initial : [
            ("number", get_numbering_preview("number", initial), "Use numbers. Negative numbers are shown with brackets"),
            ("number_ext", get_numbering_preview("number_ext", initial), "Use numbers padded with zeroes to a fixed length based on the number of objects selected. Negative numbers are shown with brackets."),
            ("lower_letter", get_numbering_preview("lower_letter", initial), "Use lowercase letters, continuing with aa, ab, ... where negative numbers are shown with brackets."),
            ("upper_letter", get_numbering_preview("upper_letter", initial), "Use uppercase letters, continuing with AA, AB, ... where negative numbers are shown with brackets."),
    ]

    custom_storey_enum = [("custom", "Custom", "Use custom numbering for storeys")]

    element_numbering: bpy.props.EnumProperty(
        name="{E}",
        description="Select numbering system for element numbering",
        items=lambda self, context: self.numberings_enum(self.initial_element_number),
        update=update_format_preview
    )    # pyright: ignore[reportInvalidTypeForm]

    type_numbering: bpy.props.EnumProperty(
        name="{T}",
        description="Select numbering system for numbering within types",
        items=lambda self, context: self.numberings_enum(self.initial_type_number),
        update=update_format_preview
    )    # pyright: ignore[reportInvalidTypeForm]

    def update_storey_numbering(self, context):
        if self.storey_numbering == "custom":
            self.initial_storey_number = 0
    
    storey_numbering: bpy.props.EnumProperty(
        name="{S}",
        description="Select numbering system for numbering storeys. Storeys are numbered in positive Z-order by default.",
        items=lambda self, context: self.numberings_enum(self.initial_storey_number) + self.custom_storey_enum,
        update=update_storey_numbering
    )    # pyright: ignore[reportInvalidTypeForm]

    #Properties for custom storey numbering
    def update_custom_storey(self, context):
        storeys = get_storeys(self)
        storey = next((storey for storey in storeys if storey.Name == self.custom_storey), None)
        _, number, _ = get_number(storey, (False, True, False))
        if number is None:
            number = storeys.index(storey)
        self["_custom_storey_number"] = int(number)

    def get_custom_storey_number(self):
        return int(self.get("_custom_storey_number", 0))

    def set_custom_storey_number(self, value):
        storey = next((storey for storey in get_storeys(self) if storey.Name == self.custom_storey), None)
        set_number(storey, (None, str(value), None), (False, True, False))
        self["_custom_storey_number"] = value

    custom_storey: bpy.props.EnumProperty(
        name = "Storey",
        description = "Select storey to number",
        items = lambda self, _: [(storey.Name, storey.Name, f"{storey.Name}\nID: {storey.GlobalId}") for storey in get_storeys(self)],
        update = update_custom_storey
    ) # pyright: ignore[reportInvalidTypeForm]

    custom_storey_number: bpy.props.IntProperty(
        name = "Storey number",
        description = f"Set custom storey number for selected storey, stored in the {pset_numbering_name} property set of the IFC element",
        get = get_custom_storey_number,
        set = set_custom_storey_number
    ) # pyright: ignore[reportInvalidTypeForm]
    
    format: bpy.props.StringProperty(
        name="Format",
        description="Format string for selected IFC type.\n" \
        "{E}: element number \n" \
        "{T}: number within type, \n" \
        "{S}: number of storey\n" \
        "[T]: first letter of type name\n" \
        "[TT] : all capitalized letters in type name\n" \
        "[TF]: full type name",
        default="E{E}S{S}[T]{T}",
        update=update_format_preview
    ) # pyright: ignore[reportInvalidTypeForm]

    save_prop : bpy.props.EnumProperty(
        name="Store number in",
        items = [("Tag", "Tag", "Store number in IFC Tag property"),
                 ("Pset_Numbering", "Pset_Numbering", "Store number in occurrence property set called " + pset_numbering_name)
                 #("Pset_Common", "Pset_Common", "Store number in reference property of the common Pset of the IFC type")
        ],
        default = "Tag"
    ) # pyright: ignore[reportInvalidTypeForm]

    remove_toggle: bpy.props.BoolProperty(
        name="Remove numbers from unselected objects",
        description="Remove numbers from unselected objects in the scene",
        default=True
    ) # pyright: ignore[reportInvalidTypeForm]

    check_duplicates_toggle: bpy.props.BoolProperty(
        name="Check for duplicate numbers",
        description="Check for duplicate numbers in all objects in the scene",
        default=True
    ) # pyright: ignore[reportInvalidTypeForm]

    # Draw method (UI layout)
    def draw(self, layout):

        # Settings box
        box = layout.box()
        box.label(text="Settings")
        grid = box.grid_flow(row_major=True, align=True, columns=4, even_columns=True)
        grid.prop(self, "settings_name", text="Name")
        grid.operator("ifc.save_settings", icon="FILE_TICK", text="Save")
        grid.operator("ifc.clear_settings", icon="CANCEL", text="Clear")
        grid.operator("ifc.export_settings", icon="EXPORT", text="Export")

        grid.prop(self, "saved_settings", text="")
        grid.operator("ifc.load_settings", icon="FILE_REFRESH", text="Load")
        grid.operator("ifc.delete_settings", icon="TRASH", text="Delete")
        grid.operator("ifc.import_settings", icon="IMPORT", text="Import")
       

        # Selection box
        box = layout.box()
        box.label(text="Elements to number:")
        row = box.row(align=False)
        row.alignment = "LEFT"
        row.prop(self, "selected_toggle")
        row.prop(self, "visible_toggle")

        rows = box.grid_flow(row_major=True, align=True, columns=4)
        rows.prop(self, "selected_types", expand=True)

        # Numbering order box
        box = layout.box()
        box.label(text="Numbering order")
        # Create a grid for direction and precision
        grid = box.grid_flow(row_major=True, align=False, columns=4, even_columns=True)
        grid.label(text="Direction: ")
        grid.prop(self, "x_direction", text="X")
        grid.prop(self, "y_direction", text="Y")
        grid.prop(self, "z_direction", text="Z")
        grid.label(text="Precision: ")
        grid.prop(self, "precision", index=0, text="X")
        grid.prop(self, "precision", index=1, text="Y")
        grid.prop(self, "precision", index=2, text="Z")

        # Axis order and reference point 
        grid = box.grid_flow(row_major=True, align=True, columns=4)
        grid.label(text="Order:")
        grid.prop(self, "axis_order", text="")
        grid.label(text="Reference point:")
        grid.prop(self, "location_type", text="")

        # Numbering systems box
        box = layout.box()
        box.label(text="Numbering of elements {E}, within type {T} and storeys {S}")
        grid = box.grid_flow(row_major=True, align=False, columns=4, even_columns=True)
        grid.label(text="Start at:")
        grid.prop(self, "initial_element_number", text="{E}")
        grid.prop(self, "initial_type_number", text="{T}")
        grid.prop(self, "initial_storey_number", text="{S}")
        grid.label(text="System:")
        grid.prop(self, "element_numbering", text="{E}")
        grid.prop(self, "type_numbering", text="{T}")
        grid.prop(self, "storey_numbering", text="{S}")

        # Custom storey number
        if self.storey_numbering == "custom":
            box = box.box()
            row = box.row(align=False)
            row.prop(self, "custom_storey", text="Storey")
            row.prop(self, "custom_storey_number", text="Number")

        # Numbering format box
        box = layout.box()
        box.label(text="Numbering format")

        grid = box.grid_flow(align=False, columns=4, even_columns=True)
        grid.label(text="Format:")
        grid.prop(self, "format", text="")
        # Show preview in a textbox style (non-editable)
        grid.label(text="Preview:")
        preview_box = grid.box()
        preview_box.label(text=self.get("_format_preview", get_format_preview(self)))

        # Storage options
        box = layout.box()
        box.label(text="Assignment options")
        row = box.row(align=True)
        row.prop(self, "save_prop", text="Store number in")
        box.prop(self, "remove_toggle")
        box.prop(self, "check_duplicates_toggle")

        # Actions
        layout.separator()
        row = layout.row(align=True)
        row.operator("ifc.assign_number", icon="TAG", text="Assign numbers")
        
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

def save_prop_to_bool(save_prop):
    return (save_prop == "Tag", save_prop=="Pset_Numbering", save_prop=="Pset_Common")

def get_common_pset(element):
    """Get the common property set for the type of an element. If not found, return any pset with 'Common' in its name."""
    ifc_type = element.is_a()
    pset_common_name = 'Pset_' + (str(ifc_type).replace('Ifc','')) + 'Common'
    return None

def get_number(element, save_prop=(True, True, True)):
    tag, prop, prop_common = None, None, None
    if save_prop[0] and hasattr(element, "Tag"):
        tag = element.Tag
    if save_prop[1] and (pset := ifc_el.get_pset(element, pset_numbering_name)):
        prop = pset.get("Number")
    if save_prop[2] and (pset := get_common_pset(element)):
        for prop in pset.HasProperties:
            if prop.Name == "Reference":
                prop_common = prop
    return (tag, prop, prop_common)

def set_number(element, number, save_prop=(True, True, True)):
    count = 0
    if save_prop[0] and hasattr(element, "Tag"):
        count += element.Tag != number[0]
        element.Tag = number[0]

    if save_prop[1]:
        property_name = "Number"
        if pset := ifc_el.get_pset(element, pset_numbering_name):
            count += pset.get(property_name) != number[1]
            pset = ifc_file.by_id(pset["id"])  
        else:
            count += number[1] is not None
            pset = ifc_api.run("pset.add_pset", ifc_file, product=element, name=pset_numbering_name) 
        if number[1] is None:
            ifc_api.run("pset.remove_pset", ifc_file, product=element, pset=pset)
        else:    
            ifc_api.run("pset.edit_pset", ifc_file, pset=pset, properties={property_name: number[1]})
    if save_prop[2]:
        property_name = "Reference"
        if pset := get_common_pset(element):
            count += get_number(element, (False, False, True))[2] != number[2]
            ifc_api.run("pset.edit_pset", ifc_file, pset=pset, properties={property_name: number[2]})
    return count

def remove_number(element, save_prop):
    return set_number(element, (None, None, None), save_prop_to_bool(save_prop))

def assign_numbers(self, props):
    """Assign numbers to selected objects based on their IFC type and location."""
    number_count = 0
    remove_count = 0

    if props.save_prop == "Pset_Common":
        self.report({'WARNING'}, "Saving to Pset Common is not yet supported")
        return {'CANCELLED'}

    if props.remove_toggle:
        #Remove existing numbers
        for obj in bpy.context.scene.objects:
            if (props.selected_toggle and obj not in bpy.context.selected_objects) or \
               (props.visible_toggle and not obj.visible_get()):
                element = tool.Ifc.get_entity(obj)
                if element is not None and element.is_a("IfcElement"):
                    remove_count += remove_number(element, props.save_prop)

    objects = bpy.context.selected_objects if props.selected_toggle else bpy.context.scene.objects
    
    if props.visible_toggle:
        objects = [obj for obj in objects if obj.visible_get()]

    if not objects:
        self.report({'WARNING'}, f"No objects selected or available for numbering, removed {remove_count} existing numbers.")
        return {'CANCELLED'}
    
    selected_types = props.selected_types
    possible_types = [tupl[0] for tupl in _possible_types]
    if "IfcElement" in selected_types:
        selected_types = possible_types
    
    elements = []
    for obj in objects: 
        element = tool.Ifc.get_entity(obj)
        if element is None:
            continue
        if element.is_a() in selected_types:
            location = get_object_location(obj, props)
            dimensions = get_object_dimensions(obj)
            elements.append((element, location, dimensions))
        elif props.remove_toggle and element.is_a() in possible_types:
            remove_count += remove_number(element, props.save_prop)

    if not elements:
        self.report({'WARNING'}, f"No elements selected or available for numbering, removed {remove_count} existing numbers.")
        return {'CANCELLED'}

    elements.sort(key=ft.cmp_to_key(lambda a, b: cmp_within_precision(a[2], b[2], props, use_dir=False)))

    elements.sort(key=ft.cmp_to_key(lambda a, b: cmp_within_precision(a[1], b[1], props)))

    storeys = get_storeys(props)

    ifc_types = [t[0] for t in load_types(objects)[0]]
    elements_by_type = [[element for (element, _, _) in elements if element.is_a() == ifc_type] for ifc_type in ifc_types]

    for (element_number, (element, _, _)) in enumerate(elements):

        type_index = ifc_types.index(element.is_a())
        type_elements = elements_by_type[type_index]
        type_number = type_elements.index(element)
        type_name = ifc_types[type_index][3:]

        if structure := element.ContainedInStructure:
            storey = structure[0].RelatingStructure
            if storey and props.storey_numbering == "custom":
                storey_number = get_number(storey, (False, True))[1]
                if storey_number is not None:
                    storey_number = int(storey_number)
            else:
                storey_number = storeys.index(storey) if storey in storeys else None
        elif "{S}" in props.format:
            self.report({'WARNING'}, f"Element {element.Name} with ID {element.GlobalId} is not contained in any storey.")

        number = format_number(props, (element_number, type_number, storey_number), (len(objects), len(type_elements), len(storeys)), type_name)
        number_count += set_number(element, (number, number, number), save_prop_to_bool(props.save_prop))

    self.report({'INFO'}, f"Renumbered {number_count} objects, removed number from {remove_count} objects.")

    if props.check_duplicates_toggle:
        #Check for duplicate numbers
        tags = []
        pset_numbers = []
        pset_commons = []
        for obj in bpy.context.scene.objects:
            element = tool.Ifc.get_entity(obj)
            tag, pset_number, pset_common = get_number(element, save_prop_to_bool(props.save_prop))
            if not element.is_a("IfcElement"):
                continue
            if tag in tags or pset_number in pset_numbers or pset_common in pset_commons:
                self.report({'WARNING'}, f"The model contains duplicate numbers")
                break
            if props.save_prop == "Tag" and tag is not None:
                tags.append(tag)
            if props.save_prop == "Pset_Numbering" and pset_number is not None:
                pset_numbers.append(pset_number)
            if props.save_prop == "Pset_Common" and pset_common is not None:
                pset_commons.append(pset_common)
    return {'FINISHED'}

class IFC_AssignNumber(bpy.types.Operator):
    bl_idname = "ifc.assign_number"
    bl_label = "Assign numbers"
    bl_description = "Assign numbers to selected objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        IfcStore.begin_transaction(self)
        old_value = {obj.name: get_number(tool.Ifc.get_entity(obj)) for obj in bpy.context.scene.objects}
        props = context.scene.ifc_numbering_settings
        result = assign_numbers(self, props)
        new_value = {obj.name: get_number(tool.Ifc.get_entity(obj)) for obj in bpy.context.scene.objects}
        self.transaction_data = {"old_value": old_value, "new_value": new_value}
        IfcStore.add_transaction_operation(self)
        IfcStore.end_transaction(self)
        return result

    def rollback(self, data):
        rollback_count = 0
        for obj in bpy.context.scene.objects:
            old_number = data["old_value"].get(obj.name, (None, None, None))
            element = tool.Ifc.get_entity(obj)
            if element and old_number != get_number(element):
                set_number(element, old_number)
                rollback_count += 1
        bpy.ops.ifc.show_message('EXEC_DEFAULT', message=f"Rollback {rollback_count} numbers.")
        return {'FINISHED'}
    
    def commit(self, data):
        commit_count = 0
        for obj in bpy.context.scene.objects:
            new_number = data["new_value"].get(obj.name, (None, None, None))
            element = tool.Ifc.get_entity(obj)
            if element and new_number != get_number(element):
                set_number(element, new_number)
                commit_count += 1
        bpy.ops.ifc.show_message('EXEC_DEFAULT', message=f"Commit {commit_count} numbers.")

class IFC_ShowMessage(bpy.types.Operator):
    bl_idname = "ifc.show_message"
    bl_label = "Show Message"
    bl_description = "Show a message in the info area"
    message: bpy.props.StringProperty() # pyright: ignore[reportInvalidTypeForm]

    def execute(self, context):
        self.report({'INFO'}, self.message)
        return {'FINISHED'}
    
#Numbering tool settings saving and loading
project = ifc_file.by_type("IfcProject")[0]

settings_dict = lambda props: {
    "selected_toggle": props.selected_toggle,
    "selected_types": list(props.selected_types),
    "visible_toggle": props.visible_toggle,
    "x_direction": props.x_direction,
    "y_direction": props.y_direction,
    "z_direction": props.z_direction,
    "axis_order": props.axis_order,
    "location_type": props.location_type,
    "precision": str((props.precision[0], props.precision[1], props.precision[2])),
    "initial_element_number": props.initial_element_number,
    "initial_type_number": props.initial_type_number,
    "initial_storey_number": props.initial_storey_number,
    "element_numbering": props.element_numbering,
    "type_numbering": props.type_numbering,
    "storey_numbering": props.storey_numbering,
    "format": props.format,
    "save_prop": props.save_prop,
    "remove_toggle": str(props.remove_toggle),
    "check_duplicates_toggle": str(props.check_duplicates_toggle),
}

def save_settings(self, props):
    """Save the numbering settings to the IFC file."""
    # Save multiple settings by name in a dictionary
    settings_name = props.settings_name.strip()
    if not settings_name:
        self.report({'ERROR'}, "Please enter a name for the settings.")
        return {'CANCELLED'}
    if pset_settings := ifc_el.get_pset(project, pset_settings_name):
        pset_settings = ifc_file.by_id(pset_settings["id"])
    else:
        pset_settings = ifc_api.run("pset.add_pset", ifc_file, product=project, name=pset_settings_name)
    if not pset_settings:
        self.report({'ERROR'}, "Could not create property set")
        return {'CANCELLED'}
    ifc_api.run("pset.edit_pset", ifc_file, pset=pset_settings, properties={settings_name: json.dumps(settings_dict(props))})
    self.report({'INFO'}, f"Saved settings '{settings_name}' to IFCProject element")
    return {'FINISHED'}

def read_settings(self, settings, props):
    for key, value in settings.items():
        if key == "selected_types":
            possible_type_names = [t[0] for t in _possible_types]
            value = set([type_name for type_name in value if type_name in possible_type_names])
        if key == "precision":
            value = tuple(map(int, value.strip("()").split(",")))
        if value == "True" or value == "False":
            value = (value=="True")
        try:
            setattr(props, key, value)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to set property '{key}': {e}")

def get_settings_names():
    project = ifc_file.by_type("IfcProject")[0]
    if pset := ifc_el.get_pset(project, pset_settings_name):
        names = list(pset.keys())
        names.remove("id")
        return names
    else:
        return []

def load_settings(self, props):
    # Load selected settings by name
    settings_name = props.saved_settings
    if settings_name == "NONE":
        self.report({'WARNING'}, "No saved settings to load.")
        return {'CANCELLED'}
    if pset_settings := ifc_el.get_pset(project, pset_settings_name):
        settings = pset_settings.get(settings_name, None)
        if settings is None:
            self.report({'WARNING'}, f"Settings '{settings_name}' not found.")
            return {'CANCELLED'}
        settings = json.loads(settings)
        read_settings(self, settings, props)
        self.report({'INFO'}, f"Loaded settings '{settings_name}' from IFCProject element")
        return {'FINISHED'}
    else:
        self.report({'WARNING'}, "No settings found")
        return {'CANCELLED'}

def delete_settings(self, props):
    settings_name = props.saved_settings
    if settings_name == "NONE":
        self.report({'WARNING'}, "No saved settings to delete.")
        return {'CANCELLED'}
    if pset_settings := ifc_el.get_pset(project, pset_settings_name):
        if settings_name in pset_settings:
            pset_settings = ifc_file.by_id(pset_settings["id"])
            ifc_api.run("pset.edit_pset", ifc_file, pset=pset_settings, properties={settings_name: None}, should_purge=True)
            self.report({'INFO'}, f"Deleted settings '{settings_name}' from IFCProject element")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, f"Settings '{settings_name}' not found.")
            return {'CANCELLED'}
    else:
        self.report({'WARNING'}, "No settings found")
        return {'CANCELLED'}

def clear_settings(self, props):
    if pset_settings := ifc_el.get_pset(project, pset_settings_name):
        pset_settings = ifc_file.by_id(pset_settings["id"])
        ifc_api.run("pset.remove_pset", ifc_file, product=project, pset=pset_settings)
        self.report({'INFO'}, f"Cleared settings from IFCProject element")
        return {'FINISHED'}
    else:
        self.report({'WARNING'}, "No settings found")
        return {'CANCELLED'}

class IFC_SaveSettings(bpy.types.Operator):
    bl_idname = "ifc.save_settings"
    bl_label = "Save Settings"
    bl_description = f"Save the current numbering settings to {pset_settings_name} of the IFC Project element, under the selected name"

    def execute(self, context):
        props = context.scene.ifc_numbering_settings
        return save_settings(self, props)
    
class IFC_LoadSettings(bpy.types.Operator):
    bl_idname = "ifc.load_settings"
    bl_label = "Load Settings"
    bl_description = f"Load the selected numbering settings from {pset_settings_name} of the IFC Project element"

    def execute(self, context):
        props = context.scene.ifc_numbering_settings
        return load_settings(self, props)

class IFC_DeleteSettings(bpy.types.Operator):
    bl_idname = "ifc.delete_settings"
    bl_label = "Delete Settings"
    bl_description = f"Delete the selected numbering settings from {pset_settings_name} of the IFC Project element"

    def execute(self, context):
        props = context.scene.ifc_numbering_settings
        return delete_settings(self, props)

class IFC_ClearSettings(bpy.types.Operator):
    bl_idname = "ifc.clear_settings"
    bl_label = "Clear Settings"
    bl_description = f"Remove the {pset_settings_name} Pset and all the saved settings from the IFC Project element"

    def execute(self, context):
        props = context.scene.ifc_numbering_settings
        return clear_settings(self, props)

class IFC_ExportSettings(bpy.types.Operator):
    bl_idname = "ifc.export_settings"
    bl_label = "Export Settings"
    bl_description = f"Export the current numbering settings to a JSON file"
    filepath: bpy.props.StringProperty(subtype="FILE_PATH") # pyright: ignore[reportInvalidTypeForm]

    def execute(self, context):
        props = context.scene.ifc_numbering_settings
        with open(self.filepath, 'w') as f:
            json.dump(settings_dict(props), f)
        self.report({'INFO'}, f"Exported settings to {self.filepath}")
        return {'FINISHED'}

    def invoke(self, context, event):
        self.filepath = "settings.json"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
    
class IFC_ImportSettings(bpy.types.Operator):
    bl_idname = "ifc.import_settings"
    bl_label = "Import Settings"
    bl_description = f"Import numbering settings from a JSON file"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH") # pyright: ignore[reportInvalidTypeForm]

    def execute(self, context):
        props = context.scene.ifc_numbering_settings
        with open(self.filepath, 'r') as f:
            settings = json.load(f)
            read_settings(self, settings, props)
        self.report({'INFO'}, f"Imported settings from {self.filepath}")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

# UI Panel (where you see it)
class IFCNumberingTool(bpy.types.Panel):
    bl_label = "Number Assignment Tool"
    bl_idname = "VIEW3D_PT_bonsai_ifc_numbering_tool"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Numbering tool'  # This becomes the tab name!

    def draw(self, context):
        layout = self.layout
        props = context.scene.ifc_numbering_settings
        props.draw(layout)

# Registration
classes = [IFC_AssignNumber, IFC_SaveSettings, IFC_LoadSettings, IFC_ExportSettings, IFC_ImportSettings, IFC_DeleteSettings, IFC_ClearSettings,
           IFC_ShowMessage, IFC_NumberingSettings, IFCNumberingTool]

def register():   
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ifc_numbering_settings = bpy.props.PointerProperty(type=IFC_NumberingSettings)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.ifc_numbering_settings

register()