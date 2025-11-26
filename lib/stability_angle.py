import math

def calculate_stability_angle(data):
    W1 = data.get('W1', 0.0); W1f = data.get('W1f', 0.0); W1r = data.get('W1r', 0.0)
    T1f = data.get('T1f', 0.0); T1r = data.get('T1r', 0.0); H1 = data.get('H1', 0.0)
    W2 = data.get('W2', 0.0); W2f = data.get('W2f', 0.0); W2r = data.get('W2r', 0.0)
    T2f = data.get('T2f', 0.0); T2r = data.get('T2r', 0.0); H2 = data.get('H2', 0.0)
    results = {}
    try:
        results['B1'] = (W1f * T1f + W1r * T1r) / (2 * W1) if W1 != 0 else 0.0
        results['B2'] = (W2f * T2f + W2r * T2r) / (2 * W2) if W2 != 0 else 0.0
        total_W = W1 + W2
        if total_W != 0:
            results['B'] = (W1 * results['B1'] + W2 * results['B2']) / total_W
            results['H'] = (H1 * W1 + H2 * W2) / total_W
        else:
            results['B'] = 0.0; results['H'] = 0.0
        H = results['H']; B = results['B']
        if H != 0:
            results['theta1'] = math.degrees(math.atan(B / H))
        else:
            results['theta1'] = 0.0
    except Exception:
        return None
    return results
