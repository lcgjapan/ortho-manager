# Reference and design note

The QGIS center/scale-to-Google-Maps behavior was independently implemented with reference to:

- Harry King's GPL-3.0 project: https://github.com/harrydking/qgis-open-google-maps
- Google Maps URLs documentation: https://developers.google.com/maps/documentation/urls/get-started

The tab-reuse bridge is an OrthoManager addition. It uses a Manifest V3 Chrome extension to remember one Google Maps tab, update it, and close the short-lived request tab.
