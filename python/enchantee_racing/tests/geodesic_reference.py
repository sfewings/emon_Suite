"""Vincenty inverse solution on WGS84: the reference the plane model is checked against.

Test support only. Nothing in engine/ imports this, and nothing should: it is here
to prove that the cheap linear projection in engine/nav.py is accurate over the
racing area, not to be used on the boat's data path.

DESIGN 6 offers the register's MGA94 easting/northing columns as nav fixtures.
Those columns were not carried into config/marks.json, and the PFSYC inner start
mark is not in the register at all, so this serves the same purpose more directly
and with one fewer datum in the way: it is an independent implementation of the
same geometry, on the same ellipsoid, with no shared code.

Reference: T. Vincenty, "Direct and Inverse Solutions of Geodesics on the
Ellipsoid with Application of Nested Equations", Survey Review XXIII (176), 1975.
"""

import math

A = 6378137.0
F = 1.0 / 298.257223563
B = A * (1.0 - F)


def vincenty_inverse(p1, p2):
    """Return (distance in metres, initial true azimuth in degrees) from p1 to p2.

    Positions are (lat, lon) in decimal degrees. Raises ValueError if the
    iteration does not converge, which happens only for near-antipodal pairs and
    cannot arise inside a 13 km bounding box.
    """
    lat1, lon1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lon2 = math.radians(p2[0]), math.radians(p2[1])

    if abs(lat1 - lat2) < 1e-15 and abs(lon1 - lon2) < 1e-15:
        return 0.0, 0.0

    L = lon2 - lon1
    u1 = math.atan((1.0 - F) * math.tan(lat1))
    u2 = math.atan((1.0 - F) * math.tan(lat2))
    sin_u1, cos_u1 = math.sin(u1), math.cos(u1)
    sin_u2, cos_u2 = math.sin(u2), math.cos(u2)

    lam = L
    for _ in range(200):
        sin_lam, cos_lam = math.sin(lam), math.cos(lam)
        sin_sigma = math.hypot(cos_u2 * sin_lam, cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_lam)
        if sin_sigma == 0.0:
            return 0.0, 0.0
        cos_sigma = sin_u1 * sin_u2 + cos_u1 * cos_u2 * cos_lam
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cos_u1 * cos_u2 * sin_lam / sin_sigma
        cos_sq_alpha = 1.0 - sin_alpha * sin_alpha
        cos_2sigma_m = 0.0 if cos_sq_alpha == 0.0 else cos_sigma - 2.0 * sin_u1 * sin_u2 / cos_sq_alpha
        c = F / 16.0 * cos_sq_alpha * (4.0 + F * (4.0 - 3.0 * cos_sq_alpha))
        lam_next = L + (1.0 - c) * F * sin_alpha * (
            sigma + c * sin_sigma * (cos_2sigma_m + c * cos_sigma * (-1.0 + 2.0 * cos_2sigma_m**2))
        )
        if abs(lam_next - lam) < 1e-14:
            lam = lam_next
            break
        lam = lam_next
    else:
        raise ValueError("Vincenty inverse did not converge")

    u_sq = cos_sq_alpha * (A * A - B * B) / (B * B)
    big_a = 1.0 + u_sq / 16384.0 * (4096.0 + u_sq * (-768.0 + u_sq * (320.0 - 175.0 * u_sq)))
    big_b = u_sq / 1024.0 * (256.0 + u_sq * (-128.0 + u_sq * (74.0 - 47.0 * u_sq)))
    delta_sigma = (
        big_b
        * sin_sigma
        * (
            cos_2sigma_m
            + big_b
            / 4.0
            * (
                cos_sigma * (-1.0 + 2.0 * cos_2sigma_m**2)
                - big_b / 6.0 * cos_2sigma_m * (-3.0 + 4.0 * sin_sigma**2) * (-3.0 + 4.0 * cos_2sigma_m**2)
            )
        )
    )
    distance = B * big_a * (sigma - delta_sigma)

    sin_lam, cos_lam = math.sin(lam), math.cos(lam)
    azimuth = math.degrees(math.atan2(cos_u2 * sin_lam, cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_lam)) % 360.0
    return distance, azimuth
