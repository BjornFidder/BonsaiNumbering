
import bpy
import bonsai.tool as tool
from mathutils import Vector
import functools as ft
from bonsai.bim.ifc import IfcStore
import string
import ifcopenshell.api as ifc_api
from ifcopenshell.util.element import get_pset
from ifcopenshell.util.pset import PsetQto
import json
import time 

class IFC:
    def __init__(self):
        self.file = None
        self.update()

    def update(self):
        if (file := IfcStore.get_file()) != self.file:
            self.file = file
            self.project = self.file.by_type("IfcProject")[0]
            self.schema = self.file.schema
            self.pset_qto = PsetQto(self.schema)

ifc = IFC()

class SaveNumber:
    
    pset_names = []
    pset_common_names = {}
    
    @staticmethod
    def get_number(element, props):
        if element is None:
            return None
        if props.save_type == "Attribute" and hasattr(element, props.attribute_name):
            return getattr(element, props.attribute_name)
        if props.save_type == "Pset":
            pset_name = SaveNumber.get_pset_name(element, props)
            if (pset := get_pset(element, pset_name)):
                return pset.get(props.property_name)
        return None

    @staticmethod
    def save_number(element, number, props):
        if element is None:
            return 0
        if props.save_type == "Attribute" and hasattr(element, props.attribute_name):
            count = getattr(element, props.attribute_name) != number
            if props.attribute_name == "Name" and number is None:
                number = element.is_a().strip("Ifc") #Reset Name to name of type
            setattr(element, props.attribute_name, number)
            return count
        if props.save_type == "Pset":
            pset_name = SaveNumber.get_pset_name(element, props)
            if pset := get_pset(element, pset_name):
                count = pset.get(props.property_name) != number
                pset = ifc.file.by_id(pset["id"])  
            else:
                count = number is not None
                pset = ifc_api.run("pset.add_pset", ifc.file, product=element, name=pset_name)
            ifc_api.run("pset.edit_pset", ifc.file, pset=pset, properties={props.property_name: number}, should_purge=True)
            if number is None and not pset.HasProperties:
                ifc_api.run("pset.remove_pset", ifc.file, product=element, pset=pset)
            return count

    @staticmethod
    def remove_number(element, props):
        return SaveNumber.save_number(element, None, props)
        
    @staticmethod
    def get_pset_name(element, props):
        if props.pset_name == "Common":
            ifc_type = element.is_a()
            name = SaveNumber.pset_common_names.get(ifc_type, None)
            return name
        if props.pset_name == "Custom Pset":
            return props.custom_pset_name
        return props.pset_name

    @staticmethod
    def update_pset_names(prop, context):
        props = context.scene.ifc_numbering_settings
        pset_names_sets = [set(ifc.pset_qto.get_applicable_names(ifc_type)) for ifc_type in LoadSelection.get_selected_types(props)]
        intersection = set.intersection(*pset_names_sets) if pset_names_sets else set()
        SaveNumber.pset_names = [('Custom Pset', 'Custom Pset', 'Store in custom Pset with selected name'),
                                 ('Common', 'Pset_Common', 'Store in Pset common of the type, e.g. Pset_WallCommon')] + \
                                [(name, name, f"Store in Pset called {name}") for name in intersection]
    
    def get_pset_common_names(elements):
        SaveNumber.pset_common_names = {}
        for element in elements:
            ifc_type = element.is_a()
            if ifc_type in SaveNumber.pset_common_names:
                continue 
            pset_names = ifc.pset_qto.get_applicable_names(ifc_type)
            if (name_guess := "Pset_" + ifc_type.strip("Ifc") + "Common") in pset_names:
                pset_common_name = name_guess
            elif (name_guess := "Pset_" + ifc_type.strip("Ifc") + "TypeCommon") in pset_names:
                pset_common_name = name_guess
            elif common_names := [name for name in pset_names if 'Common' in name]:
                pset_common_name = common_names[0]
            else:
                pset_common_name = None
            SaveNumber.pset_common_names[ifc_type] = pset_common_name

class LoadSelection:

    objects = []
    possible_types = []
    
    @staticmethod
    def load_objects(props):
        """Load the selected objects based on the current context."""
        objects = bpy.context.selected_objects if props.selected_toggle else bpy.context.scene.objects
        if props.visible_toggle:
            objects = [obj for obj in objects if obj.visible_get()]
        return objects

    @staticmethod
    def get_selected_types(props):
        """Get the selected IFC types from the properties, processing if All types are selected"""
        selected_types = list(props.selected_types)
        if "IfcElement" in selected_types:
            selected_types = [type_tuple[0] for type_tuple in LoadSelection.possible_types[1:]]
        return selected_types
    
    @staticmethod
    def load_possible_types(objects):
        """Load the available IFC types from the selected objects."""
        if not objects:
            return [("IfcElement", "All", "element")], {"IfcElement": 0}
        
        ifc_types = [("IfcElement", "All", "element")]
        seen_types = []
        number_counts = {"IfcElement": 0}

        for obj in objects:
            element = tool.Ifc.get_entity(obj)
            if not (element and element.is_a("IfcElement")):
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

    @staticmethod
    def get_possible_types(prop, context):
        """Return the list of available types for selection."""
        props = context.scene.ifc_numbering_settings
        objects = LoadSelection.load_objects(props)
        if objects != LoadSelection.objects:
            LoadSelection.objects = objects
            ifc_types, number_counts = LoadSelection.load_possible_types(objects)
            LoadSelection.possible_types = [(id, name + f": {number_counts[id]}", "") for (id, name, _) in ifc_types]
            NumberFormatting.update_format_preview(prop, context)
            SaveNumber.update_pset_names(prop, context)
            global ifc
            ifc.update()
        return LoadSelection.possible_types

class Storeys:

    save_type = "Pset"
    pset_name = "Pset_Numbering"
    property_name = "CustomStoreyNumber"

    @staticmethod
    def get_storeys(props):
        storeys = []
        for obj in bpy.context.scene.objects:
            element = tool.Ifc.get_entity(obj)
            if element is not None and element.is_a("IfcBuildingStorey"):
                location = ObjectLocation.get_object_location(obj, props)
                storeys.append((element, location))
        storeys.sort(key=ft.cmp_to_key(lambda a, b: ObjectLocation.cmp_within_precision(a[1], b[1], props, use_dir=False)))
        storeys = [storey[0] for storey in storeys]  # Extract only the IfcBuildingStorey entities
        return storeys

    @staticmethod
    def update_custom_storey(props, context):
        storeys = Storeys.get_storeys(props)
        storey = next((storey for storey in storeys if storey.Name == props.custom_storey), None)
        number = SaveNumber.get_number(storey, Storeys)
        if number is None: # If the number is not set, use the index
            number = storeys.index(storey)
        props["_custom_storey_number"] = int(number)

    @staticmethod
    def get_custom_storey_number(props):
        return int(props.get("_custom_storey_number", 0))

    @staticmethod
    def set_custom_storey_number(props, value):
        storeys = Storeys.get_storeys(props)
        storey = next((storey for storey in storeys if storey.Name == props.custom_storey), None)
        index = storeys.index(storey)
        if value == index: # If the value is the same as the index, remove the number
            SaveNumber.save_number(storey, None, Storeys)
        else:
            SaveNumber.save_number(storey, str(value), Storeys)
        props["_custom_storey_number"] = value

    @staticmethod
    def get_storey_number(element, storeys, props):
        storey_number = None
        if structure := element.ContainedInStructure:
            storey = structure[0].RelatingStructure
            if storey and props.storey_numbering == "custom":
                storey_number = SaveNumber.get_number(storey, Storeys)
                if storey_number is not None:
                    storey_number = int(storey_number)
            if storey_number is None:
                storey_number = storeys.index(storey) if storey in storeys else None
        return storey_number

class NumberFormatting:

    format_preview = ""

    @staticmethod
    def format_number(props, number_values = (0, 0, None), max_number_values=(100, 100, 1), type_name=""):
        """Return the formatted number for the given element, type and storey number"""
        format = props.format
        if "{E}" in format:
            format = format.replace("{E}", NumberingSystems.to_numbering_string(props.initial_element_number + number_values[0], props.element_numbering, max_number_values[0]))
        if "{T}" in format:
            format = format.replace("{T}", NumberingSystems.to_numbering_string(props.initial_type_number + number_values[1], props.type_numbering, max_number_values[1]))
        if "{S}" in format:
            if number_values[2] is not None:
                format = format.replace("{S}", NumberingSystems.to_numbering_string(props.initial_storey_number + number_values[2], props.storey_numbering, max_number_values[2]))
            else:
                format = format.replace("{S}", "x")
        if "[T]" in format and len(type_name) > 0:
            format = format.replace("[T]", type_name[0])
        if "[TT]" in format and len(type_name) > 1:
            format = format.replace("[TT]", "".join([c for c in type_name if c.isupper()]))
        if "[TF]" in format:
            format = format.replace("[TF]", type_name)
        return format

    @staticmethod
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
        all_types = LoadSelection.possible_types
        if len(all_types) > 1:
            return str(all_types[1][0][3:])
        #If none selected, return "Type"
        return "Type"

    @staticmethod
    def get_max_numbers(props, type_name):
        """Return number of selected elements used in preview, based on selected types"""
        max_element, max_type, max_storey = 0, 0, 0
        if props.storey_numbering == 'number_ext':
            max_storey = len(Storeys.get_storeys(props))
        if props.element_numbering == 'number_ext' or props.type_numbering == 'number_ext':
            if not props.selected_types:
                return max_element, max_type, max_storey
            type_counts = {type_tuple[0]: int(''.join([c for c in type_tuple[1] if c.isdigit()])) \
                           for type_tuple in LoadSelection.possible_types}
            if "IfcElement" in props.selected_types:
                max_element = type_counts.get("IfcElement", 0) 
            else:
                max_element = sum(type_counts.get(t, 0) for t in props.selected_types)
            max_type = type_counts.get('Ifc' + type_name, max_element)
        return max_element, max_type, max_storey

    @staticmethod
    def update_format_preview(prop, context):
        props = context.scene.ifc_numbering_settings
        type_name = NumberFormatting.get_type_name(props)
        NumberFormatting.format_preview = NumberFormatting.format_number(props, (0, 0, 0), NumberFormatting.get_max_numbers(props, type_name), type_name)

class NumberingSystems:
    
    @staticmethod
    def to_number(i):
        """Convert a number to a string."""
        if i < 0:
            return "(" + str(-i) + ")"
        return str(i)

    @staticmethod
    def to_number_ext(i, length=2):
        """Convert a number to a string with leading zeroes."""
        if i < 0:
            return "(" + NumberingSystems.to_number_ext(-i, length) + ")"
        res = str(i)
        while len(res) < length:
            res = "0" + res
        return res

    @staticmethod
    def to_letter(i, upper=False):
        """Convert a number to a letter or sequence of letters."""
        if i == 0:
            return "0"
        if i < 0:
            return "(" + NumberingSystems.to_letter(-i, upper) + ")"
        
        num2alphadict = dict(zip(range(1, 27), string.ascii_uppercase if upper else string.ascii_lowercase))
        res = ""
        numloops = (i-1) // 26
        
        if numloops > 0:
            res = res + NumberingSystems.to_letter(numloops, upper)
            
        remainder = i % 26
        if remainder == 0:
            remainder += 26
        return res + num2alphadict[remainder]
    
    @staticmethod
    def get_numberings():
        return {
            "number": NumberingSystems.to_number,
            "number_ext": NumberingSystems.to_number_ext,
            "lower_letter": NumberingSystems.to_letter,
            "upper_letter": lambda x: NumberingSystems.to_letter(x, True)
        }

    def to_numbering_string(i, numbering_system, max_number):
        """Convert a number to a string based on the numbering system."""
        if numbering_system == "number_ext":
            # Determine the length based on the maximum number
            length = len(str(max_number))
            return NumberingSystems.to_number_ext(i, length)
        if numbering_system == "custom":
            return NumberingSystems.to_number(i)
        return NumberingSystems.get_numberings()[numbering_system](i)

    def get_numbering_preview(numbering_system, initial):
        """Get a preview of the numbering string for a given number and type."""
        numbers = [NumberingSystems.to_numbering_string(i, numbering_system, 10) for i in range(initial, initial + 3)]
        return "{0}, {1}, {2}, ...".format(*numbers)

class IFC_NumberingSettings(bpy.types.PropertyGroup):
    settings_name : bpy.props.StringProperty(
        name="Settings name",
        description="Name for saving the current settings",
        default=""
    ) # pyright: ignore[reportInvalidTypeForm]

    def get_saved_settings_items(self, context):
        settings_names = Settings.get_settings_names()
        if not settings_names:
            return [("NONE", "No saved settings", "")]
        return [(name, name, "") for name in settings_names]

    saved_settings : bpy.props.EnumProperty(
        name="Load settings",
        description="Select which saved settings to load",
        items=get_saved_settings_items
    ) # pyright: ignore[reportInvalidTypeForm]

    selected_toggle: bpy.props.BoolProperty(
        name="Selected only",
        description="Only number selected objects",
        default=False,
        update=NumberFormatting.update_format_preview
    ) # pyright: ignore[reportInvalidTypeForm]

    visible_toggle: bpy.props.BoolProperty(
        name="Visible only",
        description="Only number visible objects",
        default=False,
        update=NumberFormatting.update_format_preview
    ) # pyright: ignore[reportInvalidTypeForm]

    def update_selected_types(self, context):
        NumberFormatting.update_format_preview(self, context)
        SaveNumber.update_pset_names(self, context)

    selected_types: bpy.props.EnumProperty(
        name="Of type",
        description="Select which types of elements to number",
        items= LoadSelection.get_possible_types,
        options={'ENUM_FLAG'},
        update=update_selected_types
    ) # pyright: ignore[reportInvalidTypeForm]

    x_direction: bpy.props.EnumProperty(
        name="X",
        description="Select axis direction for numbering elements",
        items=[
            ("1", "+", "Number elements in order of increasing X coordinate"),
            ("-1", "-", "Number elements in order of decreasing X coordinate")
        ],
        default="1",
    ) # pyright: ignore[reportInvalidTypeForm]

    y_direction: bpy.props.EnumProperty(
        name="Y",
        description="Select axis direction for numbering elements",
        items=[
            ("1", "+", "Number elements in order of increasing Y coordinate"),
            ("-1", "-", "Number elements in order of decreasing Y coordinate")
        ],
        default="1"
    ) # pyright: ignore[reportInvalidTypeForm]

    z_direction: bpy.props.EnumProperty(
        name="Z",
        description="Select axis direction for numbering elements",
        items=[
            ("1", "+", "Number elements in order of increasing Z coordinate"),
            ("-1", "-", "Number elements in order of decreasing Z coordinate")
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
        update=NumberFormatting.update_format_preview
    ) # pyright: ignore[reportInvalidTypeForm]

    initial_type_number: bpy.props.IntProperty(
        name="{T}",
        description="Initial number for numbering elements within type",
        default=1,
        update=NumberFormatting.update_format_preview
    ) # pyright: ignore[reportInvalidTypeForm]

    initial_storey_number: bpy.props.IntProperty(
        name="{S}",
        description="Initial number for numbering storeys",
        default=0,
        update=NumberFormatting.update_format_preview
    ) # pyright: ignore[reportInvalidTypeForm]

    numberings_enum = lambda self, initial : [
            ("number", NumberingSystems.get_numbering_preview("number", initial), "Use numbers. Negative numbers are shown with brackets"),
            ("number_ext", NumberingSystems.get_numbering_preview("number_ext", initial), "Use numbers padded with zeroes to a fixed length based on the number of objects selected. Negative numbers are shown with brackets."),
            ("lower_letter", NumberingSystems.get_numbering_preview("lower_letter", initial), "Use lowercase letters, continuing with aa, ab, ... where negative numbers are shown with brackets."),
            ("upper_letter", NumberingSystems.get_numbering_preview("upper_letter", initial), "Use uppercase letters, continuing with AA, AB, ... where negative numbers are shown with brackets."),
    ]

    custom_storey_enum = [("custom", "Custom", "Use custom numbering for storeys")]

    element_numbering: bpy.props.EnumProperty(
        name="{E}",
        description="Select numbering system for element numbering",
        items=lambda self, context: self.numberings_enum(self.initial_element_number),
        update=NumberFormatting.update_format_preview
    )    # pyright: ignore[reportInvalidTypeForm]

    type_numbering: bpy.props.EnumProperty(
        name="{T}",
        description="Select numbering system for numbering within types",
        items=lambda self, context: self.numberings_enum(self.initial_type_number),
        update=NumberFormatting.update_format_preview
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

    custom_storey: bpy.props.EnumProperty(
        name = "Storey",
        description = "Select storey to number",
        items = lambda self, _: [(storey.Name, storey.Name, f"{storey.Name}\nID: {storey.GlobalId}") for storey in Storeys.get_storeys(self)],
        update = Storeys.update_custom_storey
    ) # pyright: ignore[reportInvalidTypeForm]

    custom_storey_number: bpy.props.IntProperty(
        name = "Storey number",
        description = f"Set custom storey number for selected storey, stored in {Storeys.pset_name} in the IFC element",
        get = Storeys.get_custom_storey_number,
        set = Storeys.set_custom_storey_number
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
        update=NumberFormatting.update_format_preview
    ) # pyright: ignore[reportInvalidTypeForm]

    save_type : bpy.props.EnumProperty(
        name="Type of number storage",
        items = [("Attribute", "Attribute", "Store number in an attribute of the IFC element"),
                 ("Pset", "Pset", "Store number in a Pset of the IFC element")
        ],
        default = "Attribute",
        update = SaveNumber.update_pset_names
    ) # pyright: ignore[reportInvalidTypeForm]

    attribute_name : bpy.props.EnumProperty(
        name="Attribute name",
        description="Name of the attribute to store the number",
        items = [("Tag", "Tag", "Store number in IFC Tag attribute"),
                 ("Name", "Name", "Store number in IFC Name attribute"),
                 ("Description", "Description", "Store number in IFC Description attribute")
                ],
        default="Tag"
    ) # pyright: ignore[reportInvalidTypeForm]
    
    def get_pset_names(self, context):
        return SaveNumber.pset_names
    
    pset_name : bpy.props.EnumProperty(
        name="Pset name",
        description="Name of the Pset to store the number",
        items = get_pset_names
    ) # pyright: ignore[reportInvalidTypeForm]

    property_name : bpy.props.StringProperty(
        name="Property name",
        description="Name of the property to store the number",
        default="Number"
    ) # pyright: ignore[reportInvalidTypeForm]

    custom_pset_name : bpy.props.StringProperty(
        name="Custom Pset name",
        description="Name of the custom Pset to store the number",
        default="Pset_Numbering"
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
        preview_box.label(text=NumberFormatting.format_preview)

        # Storage options
        box = layout.box()
        box.label(text="Store number in")
        
        grid = box.grid_flow(align=False, columns=4, even_columns=True)
        grid.prop(self, "save_type", text="")
        if self.save_type == "Attribute":
            grid.prop(self, "attribute_name", text="")
        if self.save_type == "Pset":
            grid.prop(self, "pset_name", text="")
            if self.pset_name == "Custom Pset":
                grid.prop(self, "custom_pset_name", text="")
            grid.prop(self, "property_name", text="")

        box.prop(self, "remove_toggle")
        box.prop(self, "check_duplicates_toggle")

        # Actions
        layout.separator()
        row = layout.row(align=True)
        row.operator("ifc.assign_numbers", icon="TAG", text="Assign numbers")
        row = layout.row(align=True)
        row.operator("ifc.remove_numbers", icon="X", text="Remove numbers")


class ObjectLocation:
    @staticmethod
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

    @staticmethod
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

    @staticmethod
    def cmp_within_precision(a, b, props, use_dir=True):
        """Compare two vectors within a given precision."""
        direction = (int(props.x_direction), int(props.y_direction), int(props.z_direction)) if use_dir else (1, 1, 1)
        for axis in props.axis_order:
            idx = "XYZ".index(axis)
            diff = (a[idx] - b[idx]) * direction[idx]
            if 1000 * abs(diff) > props.precision[idx]:
                return 1 if diff > 0 else -1
        return 0

class UndoSupport:
    @staticmethod
    def execute_with_undo(operator, context, method):
        """Execute a method with undo support."""
        start = time.time()
        IfcStore.begin_transaction(operator)
        props = context.scene.ifc_numbering_settings
        elements = ifc.file.by_type("IfcElement")
        if props.pset_name == "Common":
            SaveNumber.get_pset_common_names(elements)
        old_value = {element.GlobalId: SaveNumber.get_number(element, props) for element in elements}
        result = method(props)
        new_value = {element.GlobalId: SaveNumber.get_number(element, props) for element in elements}
        operator.transaction_data = {"old_value": old_value, "new_value": new_value}
        IfcStore.add_transaction_operation(operator)
        IfcStore.end_transaction(operator)
        end = time.time()
        print(f"Execution time: {end - start:.4f} seconds")
        return result
    
    @staticmethod
    def rollback(operator, data):
        """Support undo of number assignment"""
        rollback_count = 0
        props = bpy.context.scene.ifc_numbering_settings
        for element in ifc.file.by_type("IfcElement"):
            old_number = data["old_value"].get(element.GlobalId, None)
            if old_number != SaveNumber.get_number(element, props):
                SaveNumber.save_number(element, old_number, props)
                rollback_count += 1
        bpy.ops.ifc.show_message('EXEC_DEFAULT', message=f"Rollback {rollback_count} numbers.")
    
    @staticmethod
    def commit(operator, data):
        """Support redo of number assignment"""
        commit_count = 0
        props = bpy.context.scene.ifc_numbering_settings
        for obj in bpy.context.scene.objects:
            element = tool.Ifc.get_entity(obj)
            if element is not None and element.is_a("IfcElement"):
                new_number = data["new_value"].get(obj.name, None)
                if new_number != SaveNumber.get_number(element, props):
                    SaveNumber.save_number(element, new_number, props)
                    commit_count += 1
        bpy.ops.ifc.show_message('EXEC_DEFAULT', message=f"Commit {commit_count} numbers.")
    
class IFC_AssignNumbers(bpy.types.Operator):
    bl_idname = "ifc.assign_numbers"
    bl_label = "Assign numbers"
    bl_description = "Assign numbers to selected objects"
    bl_options = {"REGISTER", "UNDO"}

    def assign_numbers(self, props):
        """Assign numbers to selected objects based on their IFC type and location."""
        number_count = 0
        remove_count = 0

        if props.remove_toggle:
            for obj in bpy.context.scene.objects:
                if (props.selected_toggle and obj not in bpy.context.selected_objects) or \
                (props.visible_toggle and not obj.visible_get()):
                    element = tool.Ifc.get_entity(obj)
                    if element is not None and element.is_a("IfcElement"):
                        remove_count += SaveNumber.remove_number(element, props)

        objects = LoadSelection.load_objects(props)

        if not objects:
            self.report({'WARNING'}, f"No objects selected or available for numbering, removed {remove_count} existing numbers.")
            return {'CANCELLED'}
        
        selected_types = LoadSelection.get_selected_types(props)
        possible_types = [tupl[0] for tupl in LoadSelection.possible_types]
        
        elements = []
        for obj in objects: 
            element = tool.Ifc.get_entity(obj)
            if element is None:
                continue
            if element.is_a() in selected_types:
                location = ObjectLocation.get_object_location(obj, props)
                dimensions = ObjectLocation.get_object_dimensions(obj)
                elements.append((element, location, dimensions))
            elif props.remove_toggle and element.is_a() in possible_types:
                remove_count += SaveNumber.remove_number(element, props)

        if not elements:
            self.report({'WARNING'}, f"No elements selected or available for numbering, removed {remove_count} existing numbers.")
            return {'CANCELLED'}

        elements.sort(key=ft.cmp_to_key(lambda a, b: ObjectLocation.cmp_within_precision(a[2], b[2], props, use_dir=False)))

        elements.sort(key=ft.cmp_to_key(lambda a, b: ObjectLocation.cmp_within_precision(a[1], b[1], props)))

        storeys = Storeys.get_storeys(props)

        elements_by_type = [[element for (element, _, _) in elements if element.is_a() == ifc_type] for ifc_type in selected_types]
        
        for (element_number, (element, _, _)) in enumerate(elements):

            type_index = selected_types.index(element.is_a())
            type_elements = elements_by_type[type_index]
            type_number = type_elements.index(element)
            type_name = selected_types[type_index][3:]

            storey_number = Storeys.get_storey_number(element, storeys, props)
            if storey_number is None and "{S}" in props.format:
                self.report({'WARNING'}, f"Element {element.Name} with ID {element.GlobalId} is not contained in any storey.")

            number = NumberFormatting.format_number(props, (element_number, type_number, storey_number), (len(objects), len(type_elements), len(storeys)), type_name)
            number_count += SaveNumber.save_number(element, number, props)

        self.report({'INFO'}, f"Renumbered {number_count} objects, removed number from {remove_count} objects.")

        if props.check_duplicates_toggle:
            #Check for duplicate numbers
            numbers = []
            for obj in bpy.context.scene.objects:
                element = tool.Ifc.get_entity(obj)
                number = SaveNumber.get_number(element, props)
                if not element.is_a("IfcElement"):
                    continue
                if number in numbers:
                    self.report({'WARNING'}, f"The model contains duplicate numbers")
                    break
                if number is not None:
                    numbers.append(number)
        return {'FINISHED'}

    def execute(self, context):
        return UndoSupport.execute_with_undo(self, context, self.assign_numbers)

    def rollback(self, data):
        UndoSupport.rollback(self, data)
    
    def commit(self, data):
        UndoSupport.commit(self, data)

class IFC_RemoveNumbers(bpy.types.Operator):
    bl_idname = "ifc.remove_numbers"
    bl_label = "Remove numbers"
    bl_description = "Remove numbers from selected objects, from the selected attribute or Pset"
    bl_options = {"REGISTER", "UNDO"}

    def remove_numbers(self, props):
        """Remove numbers from selected objects"""
        remove_count = 0

        objects = bpy.context.selected_objects if props.selected_toggle else bpy.context.scene.objects
        if props.visible_toggle:
            objects = [obj for obj in objects if obj.visible_get()]

        if not objects:
            self.report({'WARNING'}, f"No objects selected or available for removal.")
            return {'CANCELLED'}
            
        for obj in objects:
            element = tool.Ifc.get_entity(obj)
            if element is not None and element.is_a("IfcElement"):
                remove_count += SaveNumber.remove_number(element, props)

        if remove_count == 0:
            self.report({'WARNING'}, f"No elements selected or available for removal.")
            return {'CANCELLED'}
        
        self.report({'INFO'}, f"Removed {remove_count} existing numbers.")
        return {'FINISHED'}
        
    def execute(self, context):
        return UndoSupport.execute_with_undo(self, context, self.remove_numbers)

    def rollback(self, data):
        UndoSupport.rollback(self, data)
    
    def commit(self, data):
        UndoSupport.commit(self, data)

class IFC_ShowMessage(bpy.types.Operator):
    bl_idname = "ifc.show_message"
    bl_label = "Show Message"
    bl_description = "Show a message in the info area"
    message: bpy.props.StringProperty() # pyright: ignore[reportInvalidTypeForm]

    def execute(self, context):
        self.report({'INFO'}, self.message)
        return {'FINISHED'}

class Settings:

    pset_name = "Pset_NumberingSettings"

    settings_names = None
    
    @staticmethod
    def get_dict(props):
        """Convert the properties to a dictionary for saving."""
        return {
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
            "save_type": props.save_type,
            "attribute_name": props.attribute_name,
            "pset_name": props.pset_name,
            "custom_pset_name": props.custom_pset_name,
            "property_name": props.property_name,
            "remove_toggle": str(props.remove_toggle),
            "check_duplicates_toggle": str(props.check_duplicates_toggle),
            }

    @staticmethod
    def save_settings(operator, props):
        """Save the numbering settings to the IFC file."""
        # Save multiple settings by name in a dictionary
        settings_name = props.settings_name.strip()
        if not settings_name:
            operator.report({'ERROR'}, "Please enter a name for the settings.")
            return {'CANCELLED'}
        if pset_settings := get_pset(ifc.project, Settings.pset_name):
            pset_settings = ifc.file.by_id(pset_settings["id"])
        else:
            pset_settings = ifc_api.run("pset.add_pset", ifc.file, product=ifc.project, name=Settings.pset_name)
            Settings.settings_names.append(settings_name)
        if not pset_settings:
            operator.report({'ERROR'}, "Could not create property set")
            return {'CANCELLED'}
        ifc_api.run("pset.edit_pset", ifc.file, pset=pset_settings, properties={settings_name: json.dumps(Settings.get_dict(props))})
        operator.report({'INFO'}, f"Saved settings '{settings_name}' to IFCProject element")
        return {'FINISHED'}

    @staticmethod
    def read_settings(operator, settings, props):
        for key, value in settings.items():
            if key == "selected_types":
                possible_type_names = [t[0] for t in LoadSelection.possible_types]
                value = set([type_name for type_name in value if type_name in possible_type_names])
            if key == "precision":
                value = tuple(map(int, value.strip("()").split(",")))
            if value == "True" or value == "False":
                value = (value=="True")
            try:
                setattr(props, key, value)
            except Exception as e:
                operator.report({'ERROR'}, f"Failed to set property '{key}': {e}")

    @staticmethod
    def get_settings_names():
        if Settings.settings_names is None:
            if pset := get_pset(ifc.project, Settings.pset_name):
                names = list(pset.keys())
                names.remove("id")
            else:
                names = []
            Settings.settings_names = names
        return Settings.settings_names

    @staticmethod
    def load_settings(operator, props):
        # Load selected settings by name
        settings_name = props.saved_settings
        if settings_name == "NONE":
            operator.report({'WARNING'}, "No saved settings to load.")
            return {'CANCELLED'}
        if pset_settings := get_pset(ifc.project, Settings.pset_name):
            settings = pset_settings.get(settings_name, None)
            if settings is None:
                operator.report({'WARNING'}, f"Settings '{settings_name}' not found.")
                return {'CANCELLED'}
            settings = json.loads(settings)
            Settings.read_settings(operator, settings, props)
            operator.report({'INFO'}, f"Loaded settings '{settings_name}' from IFCProject element")
            return {'FINISHED'}
        else:
            operator.report({'WARNING'}, "No settings found")
            return {'CANCELLED'}
    
    @staticmethod
    def delete_settings(operator, props):
        settings_name = props.saved_settings
        if settings_name == "NONE":
            operator.report({'WARNING'}, "No saved settings to delete.")
            return {'CANCELLED'}
        if pset_settings := get_pset(ifc.project, Settings.pset_name):
            if settings_name in pset_settings:
                pset_settings = ifc.file.by_id(pset_settings["id"])
                ifc_api.run("pset.edit_pset", ifc.file, pset=pset_settings, properties={settings_name: None}, should_purge=True)
                operator.report({'INFO'}, f"Deleted settings '{settings_name}' from IFCProject element")
                return {'FINISHED'}
            else:
                operator.report({'WARNING'}, f"Settings '{settings_name}' not found.")
                return {'CANCELLED'}
        else:
            operator.report({'WARNING'}, "No settings found")
            return {'CANCELLED'}

    @staticmethod
    def clear_settings(operator, props):
        if pset_settings := get_pset(ifc.project, Settings.pset_name):
            pset_settings = ifc.file.by_id(pset_settings["id"])
            ifc_api.run("pset.remove_pset", ifc.file, product=ifc.project, pset=pset_settings)
            operator.report({'INFO'}, f"Cleared settings from IFCProject element")
            return {'FINISHED'}
        else:
            operator.report({'WARNING'}, "No settings found")
            return {'CANCELLED'}

class IFC_SaveSettings(bpy.types.Operator):
    bl_idname = "ifc.save_settings"
    bl_label = "Save Settings"
    bl_description = f"Save the current numbering settings to {Settings.pset_name} of the IFC Project element, under the selected name"

    def execute(self, context):
        props = context.scene.ifc_numbering_settings
        return Settings.save_settings(self, props)
    
class IFC_LoadSettings(bpy.types.Operator):
    bl_idname = "ifc.load_settings"
    bl_label = "Load Settings"
    bl_description = f"Load the selected numbering settings from {Settings.pset_name} of the IFC Project element"

    def execute(self, context):
        props = context.scene.ifc_numbering_settings
        return Settings.load_settings(self, props)

class IFC_DeleteSettings(bpy.types.Operator):
    bl_idname = "ifc.delete_settings"
    bl_label = "Delete Settings"
    bl_description = f"Delete the selected numbering settings from {Settings.pset_name} of the IFC Project element"

    def execute(self, context):
        props = context.scene.ifc_numbering_settings
        return Settings.delete_settings(self, props)

class IFC_ClearSettings(bpy.types.Operator):
    bl_idname = "ifc.clear_settings"
    bl_label = "Clear Settings"
    bl_description = f"Remove the {Settings.pset_name} Pset and all the saved settings from the IFC Project element"

    def execute(self, context):
        props = context.scene.ifc_numbering_settings
        return Settings.clear_settings(self, props)

class IFC_ExportSettings(bpy.types.Operator):
    bl_idname = "ifc.export_settings"
    bl_label = "Export Settings"
    bl_description = f"Export the current numbering settings to a JSON file"
    filepath: bpy.props.StringProperty(subtype="FILE_PATH") # pyright: ignore[reportInvalidTypeForm]

    def execute(self, context):
        props = context.scene.ifc_numbering_settings
        with open(self.filepath, 'w') as f:
            json.dump(Settings.settings_dict(props), f)
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
            Settings.read_settings(self, settings, props)
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
classes = [IFC_AssignNumbers, IFC_RemoveNumbers, IFC_SaveSettings, IFC_LoadSettings, IFC_ExportSettings, IFC_ImportSettings, IFC_DeleteSettings, IFC_ClearSettings,
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