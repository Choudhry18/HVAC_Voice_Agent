# Seeded Data

This file documents the hardcoded service locations, office hours, and seeded technician roster used by the scheduling system.

## Service locations

The service area is based on the nearest of these three locations, with a **35-mile service radius**:

| Location | Latitude | Longitude |
| --- | ---: | ---: |
| Downtown San Antonio | 29.4241 | -98.4936 |
| Stone Oak | 29.6505 | -98.4495 |
| Alamo Ranch | 29.4867 | -98.7106 |

## Office hours and appointment windows

- **Office hours:** 8:00 AM–5:00 PM Central Time (`America/Chicago`)
- **Standard appointment start times:** 8:00 AM, 10:00 AM, 1:00 PM, and 3:00 PM
- **Standard appointment length:** 2 hours
- **Availability search window:** Today through the next 7 days

Commercial appointments may last 2–4 hours depending on the service. Standard appointment windows must finish by 5:00 PM. Every request is automatically assessed for emergency status using the reported issue, escalation context, property type, equipment details, and available weather information. Outside office hours, a qualifying emergency is automatically offered an after-hours dispatch when a qualified on-call technician is available. The caller must still accept the possible higher cost and confirm the details before it is booked. If no qualified on-call technician is available, the request is sent for staff review.

## Seeded technicians and commercial specialties

### Downtown San Antonio

| Technician | Technician ID | On call | Commercial specialties |
| --- | --- | --- | --- |
| Marcus Rivera | `tech-downtown-1` | No | Rooftop/packaged units; commercial split systems; commercial maintenance |
| Priya Shah | `tech-downtown-2` | Yes | VRV/VRF systems; controls/BMS; commissioning |

### Stone Oak

| Technician | Technician ID | On call | Commercial specialties |
| --- | --- | --- | --- |
| Dana Whitfield | `tech-stoneoak-1` | Yes | VRV/VRF systems; rooftop/packaged units; commissioning |
| Tom Ellis | `tech-stoneoak-2` | No | Boilers/hydronic systems; ventilation/indoor air quality; commercial maintenance |

### Alamo Ranch

| Technician | Technician ID | On call | Commercial specialties |
| --- | --- | --- | --- |
| Luis Ortega | `tech-alamoranch-1` | No | Chillers; controls/BMS; commissioning |
| Keisha Brown | `tech-alamoranch-2` | Yes | VRV/VRF systems; rooftop/packaged units; commercial split systems; commercial maintenance |

## Internal specialty keys

| Display name | Seeded key |
| --- | --- |
| VRV/VRF systems | `vrv_vrf` |
| Rooftop/packaged units | `rtu_packaged` |
| Commercial split systems | `commercial_split` |
| Controls/BMS | `controls_bms` |
| Chillers | `chiller` |
| Boilers/hydronic systems | `boiler_hydronic` |
| Ventilation/indoor air quality | `ventilation_iaq` |
| Commissioning | `commissioning` |
| Commercial maintenance | `commercial_maintenance` |
