# OrthoManager

OrthoManager is a QGIS plugin for orthophoto inspection workflows, designed for managing inspection vectors and orthophoto export tasks in practical production work.

## Main Features

- Create and manage inspection layers for orthophoto quality checks
- Draw and edit inspection vectors directly in QGIS
- Import existing vector data into inspection GeoPackage layers
- Organize inspection layers and free-form inspection groups
- Export inspection data to common GIS/CAD formats
- Export orthophoto outputs by map sheet or area
- Create and manage VRT-based orthophoto work layers

## Requirements

- QGIS 3.40 or later
- Windows environment tested by the maintainer

## Installation

Install the plugin from the QGIS Plugin Manager when it is available in the official QGIS plugin repository.

For manual testing, install the release ZIP from QGIS:

1. Open QGIS.
2. Open `Plugins` > `Manage and Install Plugins`.
3. Choose `Install from ZIP`.
4. Select the OrthoManager plugin ZIP.
5. Enable the plugin.

## Basic Workflow

1. Open the OrthoManager panel in QGIS.
2. Prepare or load orthophoto work layers.
3. Create inspection layers for orthophoto checks.
4. Draw, edit, import, and organize inspection vectors.
5. Export inspection vectors or orthophoto outputs as needed.

## Notes

This public version is distributed as a standard QGIS Python plugin. Source code is visible after installation, as with most QGIS Python plugins.

The plugin is developed for orthophoto inspection workflows used in Japan. Some labels and workflow details may be oriented toward Japanese production environments.

## Support

Please use GitHub Issues for bug reports and feature requests:

https://github.com/lcgjapan/ortho-manager/issues

## License

GPL-3.0-or-later. See `LICENSE`.
