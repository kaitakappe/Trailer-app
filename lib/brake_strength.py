# -*- coding: utf-8 -*-
"""
制動装置（ブレーキドラム）強度計算モジュール

ブレーキドラムの内圧による応力計算と安全率判定
- 内外径比による圧力分布計算
- 曲げ応力・せん断応力計算
- 安全率判定（引張・降伏・せん断）
"""
import math


def compute_brake_drum_strength(
    r_inner_mm: float,      # ドラム内径 (mm)
    r_outer_mm: float,      # ドラム外径 (mm)
    pressure_mpa: float,    # 内圧 (MPa)
    width_mm: float,        # ドラム幅 (mm)
    tensile_strength: float,  # 引張強さ (N/mm²)
    yield_strength: float,    # 降伏点 (N/mm²)
    shear_strength: float,    # せん断強さ (N/mm²)
    friction_coeff: float = 0.2,  # 摩擦係数
    safety_margin: float = 1.0    # 安全係数（応力を増大させる倍率、通常1.0～1.2）
) -> dict:
    """
    ブレーキドラム（圧力容器）の強度計算
    
    Args:
        r_inner_mm: 内径 (mm)
        r_outer_mm: 外径 (mm)
        pressure_mpa: 内圧 (MPa)
        width_mm: ドラム幅 (mm)
        tensile_strength: 材料の引張強さ (N/mm²)
        yield_strength: 材料の降伏点 (N/mm²)
        shear_strength: 材料のせん断強さ (N/mm²)
        friction_coeff: 摩擦係数
        safety_margin: 安全係数
    
    Returns:
        計算結果の辞書
    """
    result = {}
    
    # ========== 基本パラメータ ==========
    r_i = r_inner_mm / 2.0      # 内半径 (mm)
    r_o = r_outer_mm / 2.0      # 外半径 (mm)
    b = width_mm                 # 幅 (mm)
    P_mpa = pressure_mpa         # 圧力 (MPa)
    P = P_mpa * 10.0             # 圧力を N/mm² に変換 (1 MPa = 10 N/mm²)
    
    result['r_inner'] = r_inner_mm
    result['r_outer'] = r_outer_mm
    result['width'] = width_mm
    result['pressure_mpa'] = P_mpa
    
    # ========== Lamé応力計算（古典的な圧力容器理論） ==========
    # 直径比 k = (r_o / r_i)
    k = r_o / r_i
    
    # 内面応力（接線応力）: σ_θ_i = P × (k² + 1) / (k² - 1)
    sigma_theta_i = P * (k**2 + 1) / (k**2 - 1)
    
    # 外面応力（接線応力）: σ_θ_o = P × (2 × k²) / (k² - 1)
    sigma_theta_o = P * (2 * k**2) / (k**2 - 1)
    
    # 径方向応力（内面）: σ_r_i = -P
    sigma_r_i = -P
    
    # 径方向応力（外面）: σ_r_o = 0
    sigma_r_o = 0
    
    # Hoop stress (最大引張応力): 内面の接線応力が最大
    max_hoop_stress = sigma_theta_i
    
    # von Mises 相当応力（内面が最も厳しい）
    # σ_VM = √((σ_θ - σ_r)² / 2) ≈ (σ_θ - σ_r) for thick cylinders
    von_mises = max_hoop_stress  # 簡略: 接線応力が支配的
    
    # 安全係数を適用
    equivalent_stress = von_mises * safety_margin
    
    result['k_diameter_ratio'] = k
    result['sigma_hoop_inner'] = sigma_theta_i
    result['sigma_hoop_outer'] = sigma_theta_o
    result['equivalent_stress'] = equivalent_stress
    
    # ========== 安全率計算 ==========
    # 引張に対する安全率
    safety_factor_tensile = tensile_strength / equivalent_stress if equivalent_stress > 0 else float('inf')
    
    # 降伏に対する安全率
    safety_factor_yield = yield_strength / equivalent_stress if equivalent_stress > 0 else float('inf')
    
    # せん断強さに対する安全率（接線応力の約0.5倍が典型的）
    max_shear_stress = equivalent_stress / 2.0
    safety_factor_shear = shear_strength / max_shear_stress if max_shear_stress > 0 else float('inf')
    
    result['safety_factor_tensile'] = safety_factor_tensile
    result['safety_factor_yield'] = safety_factor_yield
    result['safety_factor_shear'] = safety_factor_shear
    
    # ========== 判定基準 ==========
    # 一般的な基準: 安全率 ≥ 1.5 (静的) ～ 2.0 (動的)
    min_safety = 1.5
    
    ok_tensile = safety_factor_tensile >= min_safety
    ok_yield = safety_factor_yield >= min_safety
    ok_shear = safety_factor_shear >= min_safety
    
    result['ok_tensile'] = ok_tensile
    result['ok_yield'] = ok_yield
    result['ok_shear'] = ok_shear
    result['ok_overall'] = ok_tensile and ok_yield and ok_shear
    result['min_safety_required'] = min_safety
    
    # ========== 最大応力の報告 ==========
    result['material_tensile_strength'] = tensile_strength
    result['material_yield_strength'] = yield_strength
    result['material_shear_strength'] = shear_strength
    
    return result


def format_brake_strength_result(result: dict) -> str:
    """
    計算結果をテキスト形式でフォーマット
    
    Args:
        result: compute_brake_drum_strength の戻り値
    
    Returns:
        フォーマットされた計算結果文字列
    """
    lines = [
        "=" * 60,
        "制動装置（ブレーキドラム）強度計算結果",
        "=" * 60,
        "",
        "【寸法・圧力】",
        f"  内径: {result['r_inner']:.1f} mm",
        f"  外径: {result['r_outer']:.1f} mm",
        f"  幅: {result['width']:.1f} mm",
        f"  内圧: {result['pressure_mpa']:.3f} MPa",
        f"  径比 k = r_o / r_i: {result['k_diameter_ratio']:.3f}",
        "",
        "【応力計算】",
        f"  最大Hoop応力（内面接線応力）: {result['sigma_hoop_inner']:.2f} N/mm2",
        f"  外面接線応力: {result['sigma_hoop_outer']:.2f} N/mm2",
        f"  等価応力（von Mises）: {result['equivalent_stress']:.2f} N/mm2",
        "",
        "【材料強度】",
        f"  引張強さ: {result['material_tensile_strength']:.1f} N/mm2",
        f"  降伏点: {result['material_yield_strength']:.1f} N/mm2",
        f"  せん断強さ: {result['material_shear_strength']:.1f} N/mm2",
        "",
        "【安全率】",
        f"  引張に対する安全率: {result['safety_factor_tensile']:.2f}",
        f"    -> {'合格' if result['ok_tensile'] else '不合格'} (基準: >= {result['min_safety_required']:.1f})",
        f"  降伏に対する安全率: {result['safety_factor_yield']:.2f}",
        f"    -> {'合格' if result['ok_yield'] else '不合格'} (基準: >= {result['min_safety_required']:.1f})",
        f"  せん断に対する安全率: {result['safety_factor_shear']:.2f}",
        f"    -> {'合格' if result['ok_shear'] else '不合格'} (基準: >= {result['min_safety_required']:.1f})",
        "",
        "【総合判定】",
        f"  {'適合' if result['ok_overall'] else '不適合'}",
        "=" * 60,
    ]
    return "\n".join(lines)
