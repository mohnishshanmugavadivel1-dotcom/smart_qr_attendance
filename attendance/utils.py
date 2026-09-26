import qrcode
import io
import base64
import math

def generate_qr_base64(data: str) -> str:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    img_str = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"

def get_qr_payload(request, token: str) -> str:
    base = request.build_absolute_uri('/').rstrip('/')
    return f"{base}/attendance/verify/?session={token}"

def haversine_meters(lat1, lon1, lat2, lon2) -> float:
    """Distance in meters between two lat/lng using Haversine."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    try:
        lat1, lon1, lat2, lon2 = map(float, (lat1, lon1, lat2, lon2))
    except:
        return None
    R = 6371000  # Earth radius meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def format_distance(m):
    if m is None:
        return "—"
    if m < 1000:
        return f"{m:.0f} m"
    return f"{m/1000:.2f} km"
