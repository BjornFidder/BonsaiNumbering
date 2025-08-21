# BonsaiNumbering
BonsaiNumbering is a Blender add-on for generating and managing sequential numbering of IFC objects and elements in your Bonsai projects. The tool integrates with Blender and Bonsai, providing a user-friendly interface for assigning unique, consistent numbers and managing IFC data directly in the 3D viewport.

## Features
See the [DEMO](Demo_BonsaiNumbering.mp4) video for a quick overview of the features.
- Assign sequential numbers to selected IFC objects or elements in Blender.
- Customizable numbering formats with support for element, type, and storey numbers.
- Save and load multiple named numbering settings directly in the IFC project file, or export settings to a JSON file.
- Store numbers in IFC attributes (Tag, Name, Description) or in property sets (custom, common, or type-specific Psets).
- Storey numbering and custom storey number assignment, with direct editing in the UI.
- Duplicate number checking and automatic removal from unselected objects.
- Undo/redo integration with Blender's history for safe editing.
- Compact, user-friendly interface accessible from the Blender sidebar.
- Integrates with Bonsai for IFC data access and editing.

## Usage
The tool is currently packaged as a single Python script file. When this Python file is run in Blender, it loads the Numbering Tool in the UI sidebar of the 3D viewport. Assign, format, and manage numbers for IFC elements, and save/load settings as needed.

## License

This project is licensed under the GNU General Public License v3.0. See the [LICENSE](LICENSE) file for details.
