import math

def stop_distance(W, Wp, Fm, Fmp, speed_kmh=50.0, margin=1.05, threshold_m=25.0):
    if Fm + Fmp <= 0:
        return math.inf, False, "合成制動力が0以下です。"
    speed_ms = speed_kmh * (1000/3600)
    D = ((W + Wp) * margin * speed_ms) / (Fm + Fmp)
    ok = D <= threshold_m
    return D, ok, f"停止距離 {D:.2f} m（閾値 {threshold_m:.1f} m）"

def parking_brake_total(W, Wp, Fs, coeff=0.2):
    required = (W + Wp) * coeff
    ok = Fs >= required
    return ok, f"要求 {required:.1f} に対して実力 {Fs:.1f}"

def parking_brake_trailer(Wp, Fsp, coeff=0.2):
    required = Wp * coeff
    ok = Fsp >= required
    return ok, f"要求 {required:.1f} に対して実力 {Fsp:.1f}"

def running_performance(W, Wp, PS, WD, c1_a=121.0, c1_b=1900.0, c2=4.0):
    GCW = W + Wp
    cond1 = c1_a * PS - c1_b > GCW
    cond2 = c2 * WD > GCW
    ok = cond1 and cond2
    return ok, cond1, cond2, f"総重量 GCW={GCW:.1f}"
