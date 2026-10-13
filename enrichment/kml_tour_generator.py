"""
Google Earth 3D Tour & gx:Tour KML Generator.
Generates interactive Google Earth KML files with cinematic camera flytos,
tilt, heading, speed calculations, and route geometry.
"""

import math
import json
import datetime
from typing import List, Dict, Any, Optional


def calculate_bearing(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculates initial compass bearing in degrees between two coordinate pairs."""
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    diff_lng = math.radians(lng2 - lng1)
    
    x = math.sin(diff_lng) * math.cos(lat2_rad)
    y = math.cos(lat1_rad) * math.sin(lat2_rad) - (math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(diff_lng))
    
    initial_bearing = math.atan2(x, y)
    bearing_deg = (math.degrees(initial_bearing) + 360.0) % 360.0
    return round(bearing_deg, 1)


def generate_earth_tour_kml(
    title: str,
    description: str,
    points: List[List[float]],
    timestamps: Optional[List[float]] = None,
    mode: str = "CYCLING",
    origin_name: Optional[str] = None,
    dest_name: Optional[str] = None
) -> str:
    """
    Builds a complete, valid Google Earth KML 2.2 with gx:Tour extensions.
    Includes LookAt camera paths with heading, pitch/tilt, and line geometry.
    """
    if not points or len(points) < 2:
        return """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document><name>Empty Route</name></Document>
</kml>"""

    coord_strings = [f"{pt[1]},{pt[0]},0" for pt in points]
    coords_block = "\n          ".join(coord_strings)

    flytos = []
    total_pts = len(points)
    
    for i in range(len(points)):
        lat, lng = points[i][0], points[i][1]
        
        if i < total_pts - 1:
            next_lat, next_lng = points[i+1][0], points[i+1][1]
            heading = calculate_bearing(lat, lng, next_lat, next_lng)
        elif i > 0:
            prev_lat, prev_lng = points[i-1][0], points[i-1][1]
            heading = calculate_bearing(prev_lat, prev_lng, lat, lng)
        else:
            heading = 0.0

        step_dur = 0.5
        if timestamps and len(timestamps) == total_pts and i < total_pts - 1:
            step_dur = max(0.2, min(5.0, (timestamps[i+1] - timestamps[i])))

        flytos.append(f"""
        <gx:FlyTo>
          <gx:duration>{step_dur:.2f}</gx:duration>
          <gx:flyToMode>smooth</gx:flyToMode>
          <LookAt>
            <longitude>{lng}</longitude>
            <latitude>{lat}</latitude>
            <altitude>0</altitude>
            <heading>{heading}</heading>
            <tilt>65</tilt>
            <range>220</range>
            <altitudeMode>relativeToGround</altitudeMode>
          </LookAt>
        </gx:FlyTo>""")

    flytos_block = "\n".join(flytos)
    
    orig_lat, orig_lng = points[0][0], points[0][1]
    dest_lat, dest_lng = points[-1][0], points[-1][1]
    orig_label = origin_name or "Start of Route"
    dest_label = dest_name or "Destination"

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"
     xmlns:gx="http://www.google.com/kml/ext/2.2"
     xmlns:kml="http://www.opengis.net/kml/2.2"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <Document>
    <name>{title}</name>
    <description>{description}</description>
    
    <Style id="redRouteStyle">
      <LineStyle>
        <color>ff1f3aef</color>
        <width>6</width>
      </LineStyle>
    </Style>
    
    <Style id="pinStyle">
      <IconStyle>
        <scale>1.2</scale>
        <Icon>
          <href>http://maps.google.com/mapfiles/kml/pushpin/red-pushpin.png</href>
        </Icon>
      </IconStyle>
    </Style>

    <Placemark>
      <name>{orig_label}</name>
      <styleUrl>#pinStyle</styleUrl>
      <Point>
        <coordinates>{orig_lng},{orig_lat},0</coordinates>
      </Point>
    </Placemark>

    <Placemark>
      <name>{dest_label}</name>
      <styleUrl>#pinStyle</styleUrl>
      <Point>
        <coordinates>{dest_lng},{dest_lat},0</coordinates>
      </Point>
    </Placemark>

    <Placemark>
      <name>{mode} Trajectory</name>
      <styleUrl>#redRouteStyle</styleUrl>
      <LineString>
        <extrude>1</extrude>
        <tessellate>1</tessellate>
        <altitudeMode>clampToGround</altitudeMode>
        <coordinates>
          {coords_block}
        </coordinates>
      </LineString>
    </Placemark>

    <gx:Tour>
      <name>3D Ride-Along: {title}</name>
      <gx:Playlist>
{flytos_block}
      </gx:Playlist>
    </gx:Tour>
  </Document>
</kml>"""
    return kml
