import math

# 車軸強度計算
# 入力:
#   W (kg): 車両総重量 (車軸にかかる総荷重とみなし分配計算)
#   wheel_count (int): 車輪数 (同一軸上で荷重を均等分配)。P = W / wheel_count。
#   d_mm (mm): 軸径
#   deltaS_mm (mm): 車軸中心～軸受中心 (荷重作用点) までの距離 ΔS
#   tensile_strength (kg/cm^2): 引張強さ θb
#   yield_strength (kg/cm^2): 降伏点 θy
# 出力 dict:
#   P, Z, M, sigma_b, sf_break, sf_yield,
#   ok_break(>1.6), ok_yield(>1.3)
# 備考: Z=π*d^3/32 (d:cm), M=P*ΔS (kg-cm), 曲げ応力 σb=M/Z
#       破断安全率= θb / (2.5*σb), 降伏安全率= θy / (2.5*σb)

def compute_axle_strength(W: float, d_mm: float, deltaS_mm: float,
                           tensile_strength: float, yield_strength: float,
                           wheel_count: int = 2):
    if any(x <= 0 for x in [W, d_mm, deltaS_mm, tensile_strength, yield_strength]) or wheel_count <= 0:
        raise ValueError("正の値を入力してください")
    P = W / float(wheel_count)  # 1輪当たり荷重
    d_cm = d_mm / 10.0
    deltaS_cm = deltaS_mm / 10.0
    Z = math.pi * d_cm ** 3 / 32.0  # cm^3
    M = P * deltaS_cm  # kg-cm
    sigma_b = M / Z  # kg/cm^2
    # 荷重倍率 2.5 倍時の比較 (仕様書画像より)
    factor = 2.5
    sf_break = tensile_strength / (factor * sigma_b)
    sf_yield = yield_strength / (factor * sigma_b)
    ok_break = sf_break > 1.6
    ok_yield = sf_yield > 1.3
    return dict(P=P, wheel_count=wheel_count, Z=Z, M=M, sigma_b=sigma_b,
                sf_break=sf_break, sf_yield=sf_yield,
                ok_break=ok_break, ok_yield=ok_yield)
