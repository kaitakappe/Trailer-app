import math
from typing import Optional

# ヒッチメンバー強度計算
# 入力:
#   P (kg): ヒッチに作用する垂直荷重 (牽引車のヒッチアーム固定点での反力)
#   H (kg): 水平方向牽引力 (ブレーキ時の後退力などを考慮)
#   L_mm (mm): ヒッチメンバーの有効長さ (球面から取り付け面までの距離)
#   d_mm (mm): ヒッチメンバーの直径 (円形の場合)
#   thickness_mm (mm): 肉厚 (角形の場合。直径 d_mm のかわりに使用)
#   material_type (str): 'round' (円形) or 'square' (角形)
#   tensile_strength (kg/cm^2): 引張強さ θb
#   yield_strength (kg/cm^2): 降伏点 θy
# 出力 dict:
#   P, H, L_mm, 荷重倍率 factor, M_vertical, M_horizontal, M_combined,
#   Z, sigma, sf_break, sf_yield,
#   ok_break(>1.6), ok_yield(>1.3), 詳細な計算結果

def compute_hitch_strength(P: float, H: float, L_mm: float, d_mm: float,
                           tensile_strength: float, yield_strength: float,
                           thickness_mm: Optional[float] = None, material_type: str = 'round',
                           factor: float = 2.5):
    """
    ヒッチメンバーの強度計算
    
    Parameters:
    -----------
    P : float
        垂直荷重 (kg)
    H : float
        水平牽引力 (kg)
    L_mm : float
        ヒッチメンバー有効長さ (mm)
    d_mm : float
        円形の場合は直径、角形の場合は辺長 (mm)
    tensile_strength : float
        引張強さ (kg/cm^2)
    yield_strength : float
        降伏点 (kg/cm^2)
    thickness_mm : float, optional
        角形の場合の肉厚 (mm)
    material_type : str
        'round' or 'square'
    factor : float
        荷重倍率 (デフォルト 2.5)
    
    Returns:
    --------
    dict : 計算結果を含む辞書
    """
    
    if any(x <= 0 for x in [P, L_mm, d_mm, tensile_strength, yield_strength]):
        raise ValueError("正の値を入力してください")
    
    L_cm = L_mm / 10.0  # mm → cm
    
    # 曲げモーメント計算
    # 垂直荷重P による曲げモーメント
    M_vertical = P * L_cm  # kg-cm
    
    # 水平牽引力H による曲げモーメント
    M_horizontal = H * L_cm  # kg-cm
    
    # 合成曲げモーメント
    M_combined = math.sqrt(M_vertical**2 + M_horizontal**2)  # kg-cm
    
    # 断面係数の計算
    if material_type == 'round':
        # 円形：直径 d_mm
        d_cm = d_mm / 10.0
        Z = math.pi * d_cm**3 / 32.0  # cm^3
    elif material_type == 'square':
        # 角形：辺長 d_mm、肉厚 thickness_mm
        if thickness_mm is None or thickness_mm <= 0:
            raise ValueError("角形の場合、肉厚を指定してください")
        
        a_cm = d_mm / 10.0  # 外辺長 (cm)
        t_cm = thickness_mm / 10.0  # 肉厚 (cm)
        b_cm = a_cm - 2 * t_cm  # 内辺長 (cm)
        
        if b_cm <= 0:
            raise ValueError("肉厚が大きすぎます")
        
        # 中抜き正方形の断面係数：Z = (a^4 - b^4) / (6*a)
        Z = (a_cm**4 - b_cm**4) / (6.0 * a_cm)  # cm^3
    else:
        raise ValueError("material_type は 'round' または 'square' で指定してください")
    
    # 曲げ応力計算
    sigma = M_combined / Z  # kg/cm^2
    
    # 安全率計算（荷重倍率 factor 倍時の比較）
    sf_break = tensile_strength / (factor * sigma)
    sf_yield = yield_strength / (factor * sigma)
    
    # 判定基準：破断安全率 > 1.6、降伏安全率 > 1.3
    ok_break = sf_break > 1.6
    ok_yield = sf_yield > 1.3
    
    return dict(
        P=P,
        H=H,
        L_mm=L_mm,
        d_mm=d_mm,
        thickness_mm=thickness_mm,
        material_type=material_type,
        factor=factor,
        L_cm=L_cm,
        M_vertical=M_vertical,
        M_horizontal=M_horizontal,
        M_combined=M_combined,
        Z=Z,
        sigma=sigma,
        sf_break=sf_break,
        sf_yield=sf_yield,
        ok_break=ok_break,
        ok_yield=ok_yield,
        tensile_strength=tensile_strength,
        yield_strength=yield_strength
    )


def format_hitch_strength_result(result: dict) -> str:
    """ヒッチメンバー強度計算結果を整形表示"""
    
    lines = [
        "========== ヒッチメンバー強度計算 ==========",
        "",
        "【入力条件】",
        f"  垂直荷重 P: {result['P']:.1f} kg",
        f"  水平牽引力 H: {result['H']:.1f} kg",
        f"  有効長さ L: {result['L_mm']:.1f} mm",
        f"  荷重倍率: {result['factor']:.1f}×",
        ""
    ]
    
    if result['material_type'] == 'round':
        lines.append(f"【寸法】")
        lines.append(f"  形状: 円形")
        lines.append(f"  直径 d: {result['d_mm']:.1f} mm")
    else:
        lines.append(f"【寸法】")
        lines.append(f"  形状: 角形")
        lines.append(f"  辺長: {result['d_mm']:.1f} mm")
        lines.append(f"  肉厚: {result['thickness_mm']:.1f} mm")
    
    lines.extend([
        "",
        "【材質】",
        f"  引張強さ θb: {result['tensile_strength']:.1f} kg/cm²",
        f"  降伏点 θy: {result['yield_strength']:.1f} kg/cm²",
        "",
        "【計算過程】",
        f"  有効長さ L: {result['L_cm']:.2f} cm",
        f"  垂直曲げモーメント M_V: {result['M_vertical']:.1f} kg·cm",
        f"  水平曲げモーメント M_H: {result['M_horizontal']:.1f} kg·cm",
        f"  合成曲げモーメント M: {result['M_combined']:.1f} kg·cm",
        f"  断面係数 Z: {result['Z']:.3f} cm³",
        "",
        "【応力計算】",
        f"  曲げ応力 σ: {result['sigma']:.2f} kg/cm²",
        f"  荷重倍率{result['factor']}倍時の応力: {result['factor'] * result['sigma']:.2f} kg/cm²",
        "",
        "【安全率】",
        f"  破断安全率 (θb/(2.5×σ)): {result['sf_break']:.2f} " +
            ("✓ OK" if result['ok_break'] else "✗ NG") + f" (基準: > 1.6)",
        f"  降伏安全率 (θy/(2.5×σ)): {result['sf_yield']:.2f} " +
            ("✓ OK" if result['ok_yield'] else "✗ NG") + f" (基準: > 1.3)",
        ""
    ])
    
    if result['ok_break'] and result['ok_yield']:
        lines.append("【判定】✓ 強度を満たしています")
    else:
        lines.append("【判定】✗ 強度不足です")
    
    lines.append("=" * 40)
    
    return "\n".join(lines)
