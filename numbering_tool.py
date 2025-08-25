
import bpy
import bonsai.tool as tool
from mathutils import Vector
import numpy as np
import functools as ft
from bonsai.bim.ifc import IfcStore
import string
import ifcopenshell.api as ifc_api
from ifcopenshell.util.element import get_pset
from ifcopenshell.util.pset import PsetQto
import ifcopenshell.geom as geom
import ifcopenshell.util.shape as ifc_shape
import json

def get_id(element):
    return getattr(element, "GlobalId", element.id())

ifc_file = IfcStore.get_file()

def update_ifc_file():
    global ifc_file
    if (ifc_file_new := IfcStore.get_file()) != ifc_file:
        ifc_file = ifc_file_new
        SaveNumber.pset_qto = PsetQto(ifc_file.schema)

class SaveNumber:
    
    pset_names = [("Custom", "Custom Pset", "")]
    pset_common_names = {}
    pset_qto = PsetQto(ifc_file.schema)

    @staticmethod
    def get_number(element, settings, numbers_cache=None):
        if element is None:
            return None
        if numbers_cache is None:
            numbers_cache = {}
        if get_id(element) in numbers_cache:
            return numbers_cache[get_id(element)]
        if settings.get("save_type") == "Attribute":
            return getattr(element, SaveNumber.get_attribute_name(settings), None)
        if settings.get("save_type") == "Pset":
            pset_name = SaveNumber.get_pset_name(element, settings)
            if (pset := get_pset(element, pset_name)):
                return pset.get(settings.get("property_name"))
        return None
        
    @staticmethod
    def save_number(ifc_file, element, number, settings, numbers_cache=None):
        if element is None:
            return None
        if numbers_cache is None:
            numbers_cache = {}
        if number == SaveNumber.get_number(element, settings, numbers_cache):
            return 0
        if settings.get("save_type") == "Attribute":
            attribute_name = SaveNumber.get_attribute_name(settings)
            if not hasattr(element, attribute_name):
                return None
            if attribute_name == "Name" and number is None:
                number = element.is_a().strip("Ifc") #Reset Name to name of type
            setattr(element, attribute_name, number)
            numbers_cache[get_id(element)] = number
            return 1
        if settings.get("save_type") == "Pset":
            pset_name = SaveNumber.get_pset_name(element, settings)
            if not pset_name:
                return None
            if pset := get_pset(element, pset_name):
                pset = ifc_file.by_id(pset["id"])  
            else:
                pset = ifc_api.run("pset.add_pset", ifc_file, product=element, name=pset_name)
            ifc_api.run("pset.edit_pset", ifc_file, pset=pset, properties={settings["property_name"]: number}, should_purge=True)
            if number is None and not pset.HasProperties:
                ifc_api.run("pset.remove_pset", ifc_file, product=element, pset=pset)
            numbers_cache[get_id(element)] = number
            return 1
        return None

    @staticmethod
    def remove_number(ifc_file, element, settings, numbers_cache=None):
        count = SaveNumber.save_number(ifc_file, element, None, settings, numbers_cache)
        return int(count or 0)

    def get_attribute_name(settings):
        if settings.get("attribute_name") == "Other":
            return settings.get("attribute_name_other")
        return settings.get("attribute_name")

    @staticmethod
    def get_pset_name(element, settings):
        if settings.get("pset_name") == "Common":
            ifc_type = element.is_a()
            name = SaveNumber.pset_common_names.get(ifc_type, None)
            return name
        if settings.get("pset_name") == "Custom Pset":
            return settings.get("custom_pset_name")
        return settings.get("pset_name")

    @staticmethod
    def update_pset_names(prop, context):
        settings = Settings.to_dict(context.scene.bonsai_numbering_settings)
        pset_names_sets = [set(SaveNumber.pset_qto.get_applicable_names(ifc_type)) for ifc_type in LoadSelection.get_selected_types(settings)]
        intersection = set.intersection(*pset_names_sets) if pset_names_sets else set()
        SaveNumber.pset_names = [('Custom Pset', 'Custom Pset', 'Store in custom Pset with selected name'),
                                 ('Common', 'Pset_Common', 'Store in Pset common of the type, e.g. Pset_WallCommon')] + \
                                [(name, name, f"Store in Pset called {name}") for name in intersection]
        
    def get_pset_common_names(elements):
        SaveNumber.pset_common_names = {}
        pset_qto = PsetQto(ifc_file.schema)
        for element in elements:
            ifc_type = element.is_a()
            if ifc_type in SaveNumber.pset_common_names:
                continue
            pset_names = pset_qto.get_applicable_names(ifc_type)
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

    all_objects = []
    selected_objects = []
    possible_types = []
    
    @staticmethod
    def get_parent_type(settings):
        """Get the parent type from the settings."""
        if settings.get("parent_type") == "Other":
            return settings.get("parent_type_other")
        return settings.get("parent_type")

    @staticmethod
    def load_selected_objects(settings):
        """Load the selected objects based on the current context."""
        objects = bpy.context.selected_objects if settings.get("selected_toggle") else bpy.context.scene.objects
        if settings.get("visible_toggle"):
            objects = [obj for obj in objects if obj.visible_get()]
        return objects

    @staticmethod
    def get_selected_types(settings):
        """Get the selected IFC types from the settings, processing if All types are selected"""
        selected_types = settings.get("selected_types", [])
        if "All" in selected_types:
            selected_types = [type_tuple[0] for type_tuple in LoadSelection.possible_types[1:]]
        return selected_types
    
    @staticmethod
    def load_possible_types(objects, parent_type):
        """Load the available IFC types and their counts from the selected elements."""
        if not objects:
            return [("All", "All", "element")], {"All": 0}
        
        ifc_types = [("All", "All", "element")]
        seen_types = []
        number_counts = {"All": 0}

        for obj in objects:
            element = tool.Ifc.get_entity(obj)
            if element is None or not element.is_a(parent_type):
                continue
            ifc_type = element.is_a() #Starts with "Ifc", which we can strip by starting from index 3 
        
            if ifc_type not in seen_types:
                seen_types.append(ifc_type) 
                ifc_types.append((ifc_type, ifc_type[3:], ifc_type[3:].lower())) # Store type as (id, name, name_lower)
                number_counts[ifc_type] = 0

            number_counts["All"] += 1
            number_counts[ifc_type] += 1
                
        ifc_types.sort(key=lambda ifc_type: ifc_type[0]) 
        
        return ifc_types, number_counts

    @staticmethod
    def update_objects(prop, context):
        settings = Settings.to_dict(context.scene.bonsai_numbering_settings)
        ifc_types, number_counts = LoadSelection.load_possible_types(LoadSelection.selected_objects, LoadSelection.get_parent_type(settings))
        LoadSelection.possible_types = [(id, name + f": {number_counts[id]}", "") for (id, name, _) in ifc_types]
        NumberFormatting.update_format_preview(prop, context)
        SaveNumber.update_pset_names(prop, context)
        update_ifc_file()

    @staticmethod
    def get_possible_types(prop, context):
        """Return the list of available types for selection."""
        props = context.scene.bonsai_numbering_settings
        settings = {"selected_toggle": props.selected_toggle, "visible_toggle": props.visible_toggle}
        all_objects = list(bpy.context.scene.objects)
        objects = LoadSelection.load_selected_objects(settings)
        if all_objects != LoadSelection.all_objects or objects != LoadSelection.selected_objects:
            LoadSelection.all_objects = all_objects
            LoadSelection.selected_objects = objects
            LoadSelection.update_objects(prop, context)
        return LoadSelection.possible_types

class Storeys:

    settings = {"save_type": "Pset",
                "pset_name": "Pset_Numbering",
                "property_name": "CustomStoreyNumber"}

    @staticmethod
    def get_storeys(settings):
        """Get all storeys from the current scene."""
        storeys = []
        storey_locations = {}
        for obj in bpy.context.scene.objects:
            element = tool.Ifc.get_entity(obj)
            if element is not None and element.is_a("IfcBuildingStorey"):
                storeys.append(element)
                storey_locations[element] = ObjectGeometry.get_object_location(obj, settings)
        storeys.sort(key=ft.cmp_to_key(lambda a, b: ObjectGeometry.cmp_within_precision(storey_locations[a], storey_locations[b], settings, use_dir=False)))
        return storeys

    @staticmethod
    def update_custom_storey(props, context):
        storeys = Storeys.get_storeys(Settings.to_dict(context.scene.bonsai_numbering_settings))
        storey = next((storey for storey in storeys if storey.Name == props.custom_storey), None)
        number = SaveNumber.get_number(storey, Storeys.settings)
        if number is None: # If the number is not set, use the index
            number = storeys.index(storey)
        props["_custom_storey_number"] = int(number)

    @staticmethod
    def get_custom_storey_number(props):
        return int(props.get("_custom_storey_number", 0))

    @staticmethod
    def set_custom_storey_number(props, value):
        storeys = Storeys.get_storeys(Settings.to_dict(props))
        storey = next((storey for storey in storeys if storey.Name == props.custom_storey), None)
        index = storeys.index(storey)
        if value == index: # If the value is the same as the index, remove the number
            SaveNumber.save_number(ifc_file, storey, None, Storeys.settings)
        else:
            SaveNumber.save_number(ifc_file, storey, str(value), Storeys.settings)
        props["_custom_storey_number"] = value

    @staticmethod
    def get_storey_number(element, storeys, settings, storeys_numbers):
        storey_number = None
        if structure := getattr(element, "ContainedInStructure", None):
            storey = getattr(structure[0], "RelatingStructure", None)
            if storey and storeys_numbers:
                storey_number = storeys_numbers.get(storey, None)
            if storey and settings.get("storey_numbering") == "custom":
                storey_number = SaveNumber.get_number(storey, Storeys.settings)
                if storey_number is not None:
                    storey_number = int(storey_number)
            if storey_number is None:
                storey_number = storeys.index(storey) if storey in storeys else None
        return storey_number

class NumberFormatting:

    format_preview = ""

    @staticmethod
    def format_number(settings, number_values = (0, 0, None), max_number_values=(100, 100, 1), type_name=""):
        """Return the formatted number for the given element, type and storey number"""
        format = settings.get("format", None)
        if format is None:
            return format
        if "{E}" in format:
            format = format.replace("{E}", NumberingSystems.to_numbering_string(settings.get("initial_element_number", 0) + number_values[0], settings.get("element_numbering"), max_number_values[0]))
        if "{T}" in format:
            format = format.replace("{T}", NumberingSystems.to_numbering_string(settings.get("initial_type_number", 0) + number_values[1], settings.get("type_numbering"), max_number_values[1]))
        if "{S}" in format:
            if number_values[2] is not None:
                format = format.replace("{S}", NumberingSystems.to_numbering_string(settings.get("initial_storey_number", 0) + number_values[2], settings.get("storey_numbering"), max_number_values[2]))
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
    def get_type_name(settings):
        """Return type name used in preview, based on selected types"""
        if not settings.get("selected_types"):
            #If no types selected, return "Type"
            return "Type"
        #Get the type name of the selected type, excluding 'IfcElement'
        types = settings.get("selected_types")  
        if 'All' in types:
            types.remove('All')
        if len(types)>0:
            return str(list(types)[0][3:])
        #If all selected, return type name of one of the selected types
        all_types = LoadSelection.possible_types
        if len(all_types) > 1:
            return str(all_types[1][0][3:])
        #If none selected, return "Type"
        return "Type"

    @staticmethod
    def get_max_numbers(settings, type_name):
        """Return number of selected elements used in preview, based on selected types"""
        max_element, max_type, max_storey = 0, 0, 0
        if settings.get("storey_numbering") == 'number_ext':
            max_storey = len(Storeys.get_storeys(settings))
        if settings.get("element_numbering") == 'number_ext' or settings.get("type_numbering") == 'number_ext':
            if not settings.get("selected_types"):
                return max_element, max_type, max_storey
            type_counts = {type_tuple[0]: int(''.join([c for c in type_tuple[1] if c.isdigit()])) \
                           for type_tuple in LoadSelection.possible_types}
            if "All" in settings.get("selected_types"):
                max_element = type_counts.get("All", 0)
            else:
                max_element = sum(type_counts.get(t, 0) for t in LoadSelection.get_selected_types(settings))
            max_type = type_counts.get('Ifc' + type_name, max_element)
        return max_element, max_type, max_storey

    @staticmethod
    def update_format_preview(prop, context):
        settings = Settings.to_dict(context.scene.bonsai_numbering_settings)
        type_name = NumberFormatting.get_type_name(settings)
        NumberFormatting.format_preview = NumberFormatting.format_number(settings, (0, 0, 0), NumberFormatting.get_max_numbers(settings, type_name), type_name)

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

class BonsaiNumberingSettings(bpy.types.PropertyGroup):
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
    
    parent_type: bpy.props.EnumProperty(
        name="Parent Type",
        description="Select the parent type for numbering",
        items=[
            ("IfcElement", "IfcElement", "Number IFC elements"),
            ("IfcProduct", "IfcProduct", "Number IFC products"),
            ("IfcGridAxis", "IfcGridAxis", "Number IFC grid axes"),
            ("Other", "Other", "Input which IFC entities to number")
        ],
        default="IfcElement",
        update = LoadSelection.update_objects
    ) # pyright: ignore[reportInvalidTypeForm]

    parent_type_other : bpy.props.StringProperty(
        name="Other Parent Type",
        description="Input which IFC entities to number",
        default="IfcElement",
        update = LoadSelection.update_objects
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
        items = lambda self, _: [(storey.Name, storey.Name, f"{storey.Name}\nID: {storey.GlobalId}") for storey in Storeys.get_storeys(Settings.to_dict(self))],
        update = Storeys.update_custom_storey
    ) # pyright: ignore[reportInvalidTypeForm]

    custom_storey_number: bpy.props.IntProperty(
        name = "Storey number",
        description = f"Set custom storey number for selected storey, stored in {Storeys.settings['pset_name']} in the IFC element",
        get = Storeys.get_custom_storey_number,
        set = Storeys.set_custom_storey_number
    ) # pyright: ignore[reportInvalidTypeForm]
    
    format: bpy.props.StringProperty(
        name="Format",
        description="Format string for selected IFC type.\n" \
        "{E}: element number \n" \
        "{T}: number within type \n" \
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
                 ("Description", "Description", "Store number in IFC Description attribute"),
                 ("AxisTag", "AxisTag", "Store number in IFC AxisTag attribute, used for IFCGridAxis"),
                 ("Other", "Other", "Input in which IFC attribute to store the number")
                ],
        default="Tag"
    ) # pyright: ignore[reportInvalidTypeForm]

    attribute_name_other : bpy.props.StringProperty(
        name="Other attribute name",
        description="Name of the other attribute to store the number",
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
        grid.operator("bonsai.save_settings", icon="FILE_TICK", text="Save")
        grid.operator("bonsai.clear_settings", icon="CANCEL", text="Clear")
        grid.operator("bonsai.export_settings", icon="EXPORT", text="Export")

        grid.prop(self, "saved_settings", text="")
        grid.operator("bonsai.load_settings", icon="FILE_REFRESH", text="Load")
        grid.operator("bonsai.delete_settings", icon="TRASH", text="Delete")
        grid.operator("bonsai.import_settings", icon="IMPORT", text="Import")
        
        # Selection box
        box = layout.box()
        box.label(text="Elements to number:")
        grid = box.grid_flow(row_major=True, align=False, columns=4, even_columns=True)
        grid.prop(self, "selected_toggle")
        grid.prop(self, "visible_toggle")
        grid.prop(self, "parent_type", text="")
        if self.parent_type == "Other":
            grid.prop(self, "parent_type_other", text="")
        else:
            grid.label(text="")

        grid = box.grid_flow(row_major=True, align=True, columns=4, even_columns=True)
        grid.prop(self, "selected_types", expand=True)

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
            if self.attribute_name == "Other":
                grid.prop(self, "attribute_name_other", text="")
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
        row.operator("bonsai.assign_numbers", icon="TAG", text="Assign numbers")
        row = layout.row(align=True)
        row.operator("bonsai.remove_numbers", icon="X", text="Remove numbers")

class ObjectGeometry:
    @staticmethod
    def get_object_location(obj, settings):
        """Get the location of a Blender object."""
        mat = obj.matrix_world
        bbox_vectors = [mat @ Vector(b) for b in obj.bound_box]

        if settings.get("location_type", "CENTER") == "CENTER":
            return 0.125 * sum(bbox_vectors, Vector())

        elif settings.get("location_type") == "BOUNDING_BOX":
            bbox_vector = Vector((0, 0, 0))
            # Determine the coordinates based on the direction and axis order
            direction = (int(settings.get("x_direction")), int(settings.get("y_direction")), int(settings.get("z_direction")))
            for i in range(3):
                if direction[i] == -1:
                    bbox_vector[i] = max(v[i] for v in bbox_vectors)
                else:
                    bbox_vector[i] = min(v[i] for v in bbox_vectors)
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
    def cmp_within_precision(a, b, settings, use_dir=True):
        """Compare two vectors within a given precision."""
        direction = (int(settings.get("x_direction", 1)), int(settings.get("y_direction", 1)), int(settings.get("z_direction", 1))) if use_dir else (1, 1, 1)
        for axis in settings.get("axis_order", "XYZ"):
            idx = "XYZ".index(axis)
            diff = (a[idx] - b[idx]) * direction[idx]
            if 1000 * abs(diff) > settings.get("precision", [0, 0, 0])[idx]:
                return 1 if diff > 0 else -1
        return 0

class ElementGeometry:
    @staticmethod
    def get_element_location(element, settings):
        """Get the location of an IFC element."""
        geom_settings = geom.settings()
        geom_settings.set("use-world-coords", True)
        shape = geom.create_shape(geom_settings, element)

        verts = ifc_shape.get_shape_vertices(shape, shape.geometry)
        if settings.get("location_type") == "CENTER":
            return np.mean(verts, axis=0)
        
        elif settings.get("location_type") == "BOUNDING_BOX":
            direction = (int(settings.get("x_direction", 1)), int(settings.get("y_direction", 1)), int(settings.get("z_direction", 1)))
            bbox_min = np.min(verts, axis=0)
            bbox_max = np.max(verts, axis=0)
            bbox_vector = np.zeros(3)
            for i in range(3):
                if direction[i] == -1:
                    bbox_vector[i] = bbox_max[i]
                else:
                    bbox_vector[i] = bbox_min[i]
            return bbox_vector
        

    @staticmethod
    def get_element_dimensions(element):
        """Get the dimensions of an IFC element."""
        geom_settings = geom.settings()
        geom_settings.set("use-world-coords", True)
        shape = geom.create_shape(geom_settings, element)

        verts = ifc_shape.get_shape_vertices(shape, shape.geometry)
        bbox_min = np.min(verts, axis=0)
        bbox_max = np.max(verts, axis=0)
        return bbox_max - bbox_min

class UndoOperator:
    @staticmethod
    def execute_with_undo(operator, context, method):
        """Execute a method with undo support."""
        IfcStore.begin_transaction(operator)
        settings = Settings.to_dict(context.scene.bonsai_numbering_settings)

        parent_type = LoadSelection.get_parent_type(settings)
        try: 
            elements = ifc_file.by_type(parent_type)
        except RuntimeError:
            operator.report({'ERROR'}, f"Parent type {parent_type} not found in {ifc_file.schema} schema.")
            return {'CANCELLED'}

        if settings.get("pset_name") == "Common":
            SaveNumber.get_pset_common_names(elements)

        old_numbers = {get_id(element): SaveNumber.get_number(element, settings) for element in elements}
        new_numbers = old_numbers.copy()

        result = method(settings, new_numbers)

        operator.transaction_data = {"old_value": old_numbers, "new_value": new_numbers}
        IfcStore.add_transaction_operation(operator)
        IfcStore.end_transaction(operator)

        bpy.context.view_layer.objects.active = bpy.context.active_object

        return result
    
    @staticmethod
    def rollback(operator, data):
        """Support undo of number assignment"""
        rollback_count = 0
        settings = Settings.to_dict(bpy.context.scene.bonsai_numbering_settings)
        for element in ifc_file.by_type(LoadSelection.get_parent_type(settings)):
            old_number = data["old_value"].get(get_id(element), None)
            rollback_count += int(SaveNumber.save_number(ifc_file, element, old_number, settings, data["new_value"]) or 0)
        bpy.ops.bonsai.show_message('EXEC_DEFAULT', message=f"Rollback {rollback_count} numbers.")
    
    @staticmethod
    def commit(operator, data):
        """Support redo of number assignment"""
        commit_count = 0
        settings = Settings.to_dict(bpy.context.scene.bonsai_numbering_settings)
        for obj in bpy.context.scene.objects:
            element = tool.Ifc.get_entity(obj)
            if element is not None and element.is_a(LoadSelection.get_parent_type(settings)):
                new_number = data["new_value"].get(obj.name, None)
                commit_count += int(SaveNumber.save_number(ifc_file, element, new_number, settings, data["old_value"]) or 0)
        bpy.ops.bonsai.show_message('EXEC_DEFAULT', message=f"Commit {commit_count} numbers.")
  
class BonsaiAssignNumbers(bpy.types.Operator):
    bl_idname = "bonsai.assign_numbers"
    bl_label = "Assign numbers"
    bl_description = "Assign numbers to selected objects"
    bl_options = {"REGISTER", "UNDO"}

    def number_elements(elements, ifc_file, settings, elements_locations = None, elements_dimensions = None, storeys = None, numbers_cache = {}, storeys_numbers={}, report=None, remove_count=None):
        """Number elements in the IFC file with the provided settings. If element locations or dimensions are specified, these are used for sorting.
        Providing numbers_cache, a dictionary with element-> currently saved number, speeds up execution.
        If storeys_numbers is provided, as a dictionary storey->number, this is used for assigning storey numbers."""
        if report is None:
            def report(report_type, message):
                if report_type == {"INFO"}:
                    print("INFO: ", message)
                if report_type == {"WARNING"}:
                    raise Exception(message)
        if storeys is None:
            storeys = []

        number_count = 0

        if elements_dimensions:
            elements.sort(key=ft.cmp_to_key(lambda a, b: ObjectGeometry.cmp_within_precision(elements_dimensions[a], elements_dimensions[b], settings, use_dir=False)))
        if elements_locations:
            elements.sort(key=ft.cmp_to_key(lambda a, b: ObjectGeometry.cmp_within_precision(elements_locations[a], elements_locations[b], settings)))

        selected_types = LoadSelection.get_selected_types(settings)

        if not selected_types:
            selected_types = list(set(element.is_a() for element in elements))

        elements_by_type = [[element for element in elements if element.is_a() == ifc_type] for ifc_type in selected_types]

        failed_types = set()
        for (element_number, element) in enumerate(elements):

            type_index = selected_types.index(element.is_a())
            type_elements = elements_by_type[type_index]
            type_number = type_elements.index(element)
            type_name = selected_types[type_index][3:]

            if storeys:
                storey_number = Storeys.get_storey_number(element, storeys, settings, storeys_numbers)
                if storey_number is None and "{S}" in settings.get("format"):
                    if report is not None:
                        report({'WARNING'}, f"Element {getattr(element, 'Name', '')} of type {element.is_a()} with ID {get_id(element)} is not contained in any storey.")
                    else:
                        raise Exception(f"Element {getattr(element, 'Name', '')} of type {element.is_a()} with ID {get_id(element)} is not contained in any storey.")
            else:
                storey_number = None
            
            number = NumberFormatting.format_number(settings, (element_number, type_number, storey_number), (len(elements), len(type_elements), len(storeys)), type_name)
            count = SaveNumber.save_number(ifc_file, element, number, settings, numbers_cache)
            if count is None:
                report({'WARNING'}, f"Failed to save number for element {getattr(element, 'Name', '')} of type {element.is_a()} with ID {get_id(element)}.")
                failed_types.add(element.is_a())
            else:
                number_count += count

        if failed_types:
            report({'WARNING'}, f"Failed to renumber the following types: {failed_types}")

        if settings.get("remove_toggle") and remove_count is not None:
            report({'INFO'}, f"Renumbered {number_count} objects, removed number from {remove_count} objects.")
        else:
            report({'INFO'}, f"Renumbered {number_count} objects.")

        return {'FINISHED'}, number_count

    def assign_numbers(self, settings, numbers_cache):
        """Assign numbers to selected objects based on their IFC type and location."""
        remove_count = 0

        if settings.get("remove_toggle"):
            for obj in bpy.context.scene.objects:
                if (settings.get("selected_toggle") and obj not in bpy.context.selected_objects) or \
                (settings.get("visible_toggle") and not obj.visible_get()):
                    element = tool.Ifc.get_entity(obj)
                    if element is not None and element.is_a(LoadSelection.get_parent_type(settings)):
                        count_diff = SaveNumber.remove_number(ifc_file, element, settings, numbers_cache)
                        remove_count += count_diff

        objects = LoadSelection.load_selected_objects(settings)

        if not objects:
            self.report({'WARNING'}, f"No objects selected or available for numbering, removed {remove_count} existing numbers.")
            return {'CANCELLED'}
        
        selected_types = LoadSelection.get_selected_types(settings)
        possible_types = [tupl[0] for tupl in LoadSelection.possible_types]
        
        selected_elements = []
        elements_locations = {}
        elements_dimensions = {}
        for obj in objects: 
            element = tool.Ifc.get_entity(obj)
            if element is None:
                continue
            if element.is_a() in selected_types:
                selected_elements.append(element)
                elements_locations[element] = ObjectGeometry.get_object_location(obj, settings)
                elements_dimensions[element] = ObjectGeometry.get_object_dimensions(obj)
            elif settings.get("remove_toggle") and element.is_a() in possible_types:
                remove_count += SaveNumber.remove_number(ifc_file, element, settings, numbers_cache)
        
        if not selected_elements:
            self.report({'WARNING'}, f"No elements selected or available for numbering, removed {remove_count} existing numbers.")

        storeys = Storeys.get_storeys(settings)
        res, _= BonsaiAssignNumbers.number_elements(selected_elements, 
                                                    ifc_file, settings, 
                                                    elements_locations, 
                                                    elements_dimensions,  
                                                    storeys, 
                                                    numbers_cache,
                                                    report = self.report,
                                                    remove_count=remove_count)

        if settings.get("check_duplicates_toggle"):
            numbers = []
            for obj in bpy.context.scene.objects:
                element = tool.Ifc.get_entity(obj)
                if element is None or not element.is_a(LoadSelection.get_parent_type(settings)):
                    continue
                number = SaveNumber.get_number(element, settings, numbers_cache)
                if number in numbers:
                    self.report({'WARNING'}, f"The model contains duplicate numbers")
                    return {'FINISHED'}
                if number is not None:
                    numbers.append(number)

        return res

    def execute(self, context):
        return UndoOperator.execute_with_undo(self, context, self.assign_numbers)

    def rollback(self, data):
        UndoOperator.rollback(self, data)
    
    def commit(self, data):
        UndoOperator.commit(self, data)

class BonsaiRemoveNumbers(bpy.types.Operator):
    bl_idname = "bonsai.remove_numbers"
    bl_label = "Remove numbers"
    bl_description = "Remove numbers from selected objects, from the selected attribute or Pset"
    bl_options = {"REGISTER", "UNDO"}

    def remove_numbers(self, settings, numbers_cache):
        """Remove numbers from selected objects"""
        remove_count = 0

        objects = bpy.context.selected_objects if settings.get("selected_toggle") else bpy.context.scene.objects
        if settings.get("visible_toggle"):
            objects = [obj for obj in objects if obj.visible_get()]

        if not objects:
            self.report({'WARNING'}, f"No objects selected or available for removal.")
            return {'CANCELLED'}
            
        for obj in objects:
            element = tool.Ifc.get_entity(obj)
            if element is not None and element.is_a(LoadSelection.get_parent_type(settings)):
                remove_count += SaveNumber.remove_number(ifc_file, element, settings, numbers_cache)
                numbers_cache[get_id(element)] = None

        if remove_count == 0:
            self.report({'WARNING'}, f"No elements selected or available for removal.")
            return {'CANCELLED'}
        
        self.report({'INFO'}, f"Removed {remove_count} existing numbers.")
        return {'FINISHED'}
        
    def execute(self, context):
        return UndoOperator.execute_with_undo(self, context, self.remove_numbers)

    def rollback(self, data):
        UndoOperator.rollback(self, data)
    
    def commit(self, data):
        UndoOperator.commit(self, data)

class BonsaiShowMessage(bpy.types.Operator):
    bl_idname = "bonsai.show_message"
    bl_label = "Show Message"
    bl_description = "Show a message in the info area"
    message: bpy.props.StringProperty() # pyright: ignore[reportInvalidTypeForm]

    def execute(self, context):
        self.report({'INFO'}, self.message)
        return {'FINISHED'}

class Settings:

    pset_name = "Pset_NumberingSettings"

    settings_names = None
    
    def import_settings(filepath):
        """Import settings from a JSON file, e.g. as exported from the UI"""
        with open(filepath, 'r') as file:
            settings = json.load(file)
        return settings

    def default_settings():
        """"Return a default dictionary of settings for numbering elements."""
        return {
            "x_direction": 1,
            "y_direction": 1,
            "z_direction": 1,
            "axis_order": "ZYX",
            "location_type": "CENTER",
            "precision": (1, 1, 1),
            "initial_element_number": 1,
            "initial_type_number": 1,
            "initial_storey_number": 0,
            "element_numbering": "number",
            "type_numbering": "number",
            "storey_numbering": "number",
            "format": "E{E}S{S}[T]{T}",
            "save_type": "Attribute",
            "attribute_name": "Tag",
            "pset_name": "Common",
            "custom_pset_name": "Pset_Numbering",
            "property_name": "Number"
            }
    
    @staticmethod
    def to_dict(props):
        """Convert the properties to a dictionary for saving."""
        return {
            "selected_toggle": props.selected_toggle,
            "visible_toggle": props.visible_toggle,
            "parent_type": props.parent_type,
            "parent_type_other": props.parent_type_other,
            "selected_types": list(props.selected_types),
            "x_direction": props.x_direction,
            "y_direction": props.y_direction,
            "z_direction": props.z_direction,
            "axis_order": props.axis_order,
            "location_type": props.location_type,
            "precision": (props.precision[0], props.precision[1], props.precision[2]),
            "initial_element_number": props.initial_element_number,
            "initial_type_number": props.initial_type_number,
            "initial_storey_number": props.initial_storey_number,
            "element_numbering": props.element_numbering,
            "type_numbering": props.type_numbering,
            "storey_numbering": props.storey_numbering,
            "format": props.format,
            "save_type": props.save_type,
            "attribute_name": props.attribute_name,
            "attribute_name_other": props.attribute_name_other,
            "pset_name": props.pset_name,
            "custom_pset_name": props.custom_pset_name,
            "property_name": props.property_name,
            "remove_toggle": props.remove_toggle,
            "check_duplicates_toggle": props.check_duplicates_toggle
            }

    @staticmethod
    def save_settings(operator, props, ifc_file):
        """Save the numbering settings to the IFC file."""
        # Save multiple settings by name in a dictionary
        project = ifc_file.by_type("IfcProject")[0]
        settings_name = props.settings_name.strip()
        if not settings_name:
            operator.report({'ERROR'}, "Please enter a name for the settings.")
            return {'CANCELLED'}
        if pset_settings := get_pset(project, Settings.pset_name):
            pset_settings = ifc_file.by_id(pset_settings["id"])
        else:
            pset_settings = ifc_api.run("pset.add_pset", ifc_file, product=project, name=Settings.pset_name)
        if not pset_settings:
            operator.report({'ERROR'}, "Could not create property set")
            return {'CANCELLED'}
        ifc_api.run("pset.edit_pset", ifc_file, pset=pset_settings, properties={settings_name: json.dumps(Settings.to_dict(props))})
        Settings.settings_names.add(settings_name)
        operator.report({'INFO'}, f"Saved settings '{settings_name}' to IFCProject element")
        return {'FINISHED'}

    @staticmethod
    def read_settings(operator, settings, props):
        for key, value in settings.items():
            if key == "selected_types":
                possible_type_names = [t[0] for t in LoadSelection.possible_types]
                value = set([type_name for type_name in value if type_name in possible_type_names])
            try:
                setattr(props, key, value)
            except Exception as e:
                operator.report({'ERROR'}, f"Failed to set property {key} to {value}. Error: {e}")

    @staticmethod
    def get_settings_names():
        if Settings.settings_names is None:
            if pset := get_pset(ifc_file.by_type("IfcProject")[0], Settings.pset_name):
                names = set(pset.keys())
                names.remove("id")
            else:
                names = set()
            Settings.settings_names = names
        return Settings.settings_names

    @staticmethod
    def load_settings(operator, props, ifc_file):
        # Load selected settings by name
        settings_name = props.saved_settings
        if settings_name == "NONE":
            operator.report({'WARNING'}, "No saved settings to load.")
            return {'CANCELLED'}
        if pset_settings := get_pset(ifc_file.by_type("IfcProject")[0], Settings.pset_name):
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
        if pset_settings := get_pset(ifc_file.by_type("IfcProject")[0], Settings.pset_name):
            if settings_name in pset_settings:
                pset_settings = ifc_file.by_id(pset_settings["id"])
                ifc_api.run("pset.edit_pset", ifc_file, pset=pset_settings, properties={settings_name: None}, should_purge=True)
                Settings.settings_names.remove(settings_name)
                operator.report({'INFO'}, f"Deleted settings '{settings_name}' from IFCProject element")

                if not pset_settings.HasProperties:
                    ifc_api.run("pset.remove_pset", ifc_file, product=ifc_file.by_type("IfcProject")[0], pset=pset_settings)
                return {'FINISHED'}
            else:
                operator.report({'WARNING'}, f"Settings '{settings_name}' not found.")
                return {'CANCELLED'}
        else:
            operator.report({'WARNING'}, "No settings found")
            return {'CANCELLED'}

    @staticmethod
    def clear_settings(operator, props):
        project = ifc_file.by_type("IfcProject")[0]
        if pset_settings := get_pset(project, Settings.pset_name):
            pset_settings = ifc_file.by_id(pset_settings["id"])
            ifc_api.run("pset.remove_pset", ifc_file, product=project, pset=pset_settings)
            operator.report({'INFO'}, f"Cleared settings from IFCProject element")
            Settings.settings_names = set()
            return {'FINISHED'}
        else:
            operator.report({'WARNING'}, "No settings found")
            return {'CANCELLED'}

class BonsaiSaveSettings(bpy.types.Operator):
    bl_idname = "bonsai.save_settings"
    bl_label = "Save Settings"
    bl_description = f"Save the current numbering settings to {Settings.pset_name} of the IFC Project element, under the selected name"

    def execute(self, context):
        props = context.scene.bonsai_numbering_settings
        return Settings.save_settings(self, props, ifc_file)
    
class BonsaiLoadSettings(bpy.types.Operator):
    bl_idname = "bonsai.load_settings"
    bl_label = "Load Settings"
    bl_description = f"Load the selected numbering settings from {Settings.pset_name} of the IFC Project element"

    def execute(self, context):
        props = context.scene.bonsai_numbering_settings
        return Settings.load_settings(self, props, ifc_file)

class BonsaiDeleteSettings(bpy.types.Operator):
    bl_idname = "bonsai.delete_settings"
    bl_label = "Delete Settings"
    bl_description = f"Delete the selected numbering settings from {Settings.pset_name} of the IFC Project element"

    def execute(self, context):
        props = context.scene.bonsai_numbering_settings
        return Settings.delete_settings(self, props)

class BonsaiClearSettings(bpy.types.Operator):
    bl_idname = "bonsai.clear_settings"
    bl_label = "Clear Settings"
    bl_description = f"Remove the {Settings.pset_name} Pset and all the saved settings from the IFC Project element"

    def execute(self, context):
        props = context.scene.bonsai_numbering_settings
        return Settings.clear_settings(self, props)

class BonsaiExportSettings(bpy.types.Operator):
    bl_idname = "bonsai.export_settings"
    bl_label = "Export Settings"
    bl_description = f"Export the current numbering settings to a JSON file"
    filepath: bpy.props.StringProperty(subtype="FILE_PATH") # pyright: ignore[reportInvalidTypeForm]

    def execute(self, context):
        props = context.scene.bonsai_numbering_settings
        with open(self.filepath, 'w') as f:
            json.dump(Settings.settings_dict(props), f)
        self.report({'INFO'}, f"Exported settings to {self.filepath}")
        return {'FINISHED'}

    def invoke(self, context, event):
        self.filepath = "settings.json"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
    
class BonsaiImportSettings(bpy.types.Operator):
    bl_idname = "bonsai.import_settings"
    bl_label = "Import Settings"
    bl_description = f"Import numbering settings from a JSON file"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH") # pyright: ignore[reportInvalidTypeForm]

    def execute(self, context):
        props = context.scene.bonsai_numbering_settings
        with open(self.filepath, 'r') as f:
            settings = json.load(f)
            Settings.read_settings(self, settings, props)
        self.report({'INFO'}, f"Imported settings from {self.filepath}")
        return {'FINISHED'}
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

# UI Panel (where you see it)
class BonsaiNumberingTool(bpy.types.Panel):
    bl_label = "Number Assignment Tool"
    bl_idname = "VIEW3D_PT_bonsai_numbering_tool"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Numbering tool'  # This becomes the tab name!

    def draw(self, context):
        layout = self.layout
        props = context.scene.bonsai_numbering_settings
        props.draw(layout)

# Registration
classes = [BonsaiAssignNumbers, BonsaiRemoveNumbers, BonsaiSaveSettings, BonsaiLoadSettings, BonsaiExportSettings, BonsaiImportSettings, BonsaiDeleteSettings, BonsaiClearSettings,
           BonsaiShowMessage, BonsaiNumberingSettings, BonsaiNumberingTool]

def register():   
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bonsai_numbering_settings = bpy.props.PointerProperty(type=BonsaiNumberingSettings)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.bonsai_numbering_settings

register()

'''
#Example usage outside Blender UI

ifc_file = ifcopenshell.open("path/to/your.ifc")
SaveNumber.pset_qto = PsetQto(ifc_file.schema)

elements = ifc_file.by_type("IfcBeam")
settings = Settings.default_settings()
settings["format"] = "E{E}"

elements_locations = {element: ElementGeometry.get_element_location(element, settings) for element in elements}
elements_dimensions = {element: ElementGeometry.get_element_dimensions(element) for element in elements}

BonsaiAssignNumbers.number_elements(elements, ifc_file, settings, elements_locations, elements_dimensions)
'''