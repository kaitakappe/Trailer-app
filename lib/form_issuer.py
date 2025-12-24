"""
第1号様式（組立車）自動記入モジュール
計算結果から申請書類を生成する
"""
import os
from typing import Optional
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False

try:
    from PyPDF2 import PdfReader, PdfWriter
    _PYPDF2_AVAILABLE = True
except ImportError:
    _PYPDF2_AVAILABLE = False


class Form1Data:
    """第1号様式の記入データを格納するクラス"""
    def __init__(self):
        # 申請者情報
        self.applicant_name = ""  # 氏名又は名称
        self.applicant_address = ""  # 住所
        self.vehicle_type = "組立車"  # 自動車の種別
        
        # 車両基本情報
        self.vehicle_name = ""  # 自動車の名称
        self.vehicle_model = ""  # 型式
        self.chassis_model = ""  # シャシー型式
        self.engine_model = ""  # 原動機の型式
        
        # 寸法情報
        self.length = ""  # 長さ (mm)
        self.width = ""  # 幅 (mm)
        self.height = ""  # 高さ (mm)
        self.wheelbase = ""  # ホイールベース (mm)
        self.tread_front = ""  # トレッド(前) (mm)
        self.tread_rear = ""  # トレッド(後) (mm)
        self.overhang_front = ""  # オーバーハング(前) (mm)
        self.overhang_rear = ""  # オーバーハング(後) (mm)
        
        # 重量情報
        self.vehicle_weight = ""  # 車両重量 (kg)
        self.vehicle_total_weight = ""  # 車両総重量 (kg)
        self.max_load_weight = ""  # 最大積載量 (kg)
        
        # 性能情報
        self.max_speed = ""  # 最高速度 (km/h)
        self.engine_power = ""  # 定格出力 (kW)
        self.fuel_type = ""  # 燃料の種類
        
        # 車軸情報
        self.axle_count = ""  # 車軸数
        self.axle_weight_front = ""  # 前軸重 (kg)
        self.axle_weight_rear = ""  # 後軸重 (kg)
        
        # その他
        self.notes = ""  # 備考
        self.application_date = ""  # 申請日


class Form2Data:
    """保安基準適合検討表（ライトトレーラ用）のデータを格納するクラス"""
    def __init__(self):
        # 2条: 寸法
        self.length = ""  # 長さ (mm)
        self.width = ""  # 幅 (mm)
        self.height = ""  # 高さ (mm)
        
        # 3条: 最低地上高・車体下部突出物
        self.ground_clearance = ""  # 最低地上高 (mm)
        
        # 3条の2: 車台及び車体
        self.chassis_structure = ""  # 構造説明
        
        # 4条の2: 牽引
        self.trailer_weight = ""  # 牽引重量 (kg)
        self.coupler_type = ""  # カプラー形式
        
        # 5条: 重量等
        self.vehicle_weight = ""  # 車両重量 (kg)
        self.max_total_weight = ""  # 最大積載量含む総重量 (kg)
        self.max_load_weight = ""  # 最大積載量 (kg)
        self.axle_weight_front = ""  # 前軸重 (kg)
        self.axle_weight_rear = ""  # 後軸重 (kg)
        
        # 6条: 走行装置等の接地部
        self.tire_condition = ""  # タイヤの状態
        
        # 7条: 原動機
        self.has_engine = ""  # 原動機の有無
        
        # 8条: 燃料装置等
        self.fuel_system = ""  # 燃料装置
        
        # 9条: 潤滑装置
        self.lubrication_system = ""  # 潤滑装置
        
        # 10条: 排気管等
        self.exhaust_system = ""  # 排気管
        
        # 11条: 排出ガス発散防止装置
        self.emission_control = ""  # 排出ガス対策
        
        # 11条の2: 排気騒音防止装置
        self.noise_control = ""  # 騒音防止
        
        # 11条の3: 騒音防止性能等
        self.noise_performance = ""  # 騒音性能
        
        # 11条の4: 近接排気騒音
        self.proximity_noise = ""  # 近接排気騒音
        
        # 12条: 制動装置
        self.parking_brake = ""  # 駐車ブレーキ
        self.service_brake = ""  # 常用ブレーキ
        
        # 13条: 緩衝装置
        self.suspension = ""  # 緩衝装置
        
        # 14条: 燃料タンク
        self.fuel_tank = ""  # 燃料タンク
        
        # 15条: 操縦装置
        self.steering = ""  # 操縦装置
        
        # 16条: 施錠装置
        self.lock_device = ""  # 施錠装置
        
        # 17条: 施錠装置
        self.coupling_device = ""  # 連結装置
        
        # 17条の2: 連結装置
        self.safety_chain = ""  # 安全チェーン等
        
        # 18条: 乗車装置
        self.seating = ""  # 乗車装置
        
        # 19条: 立席
        self.standing_space = ""  # 立席
        
        # 20条: 物品積載装置
        self.cargo_device = ""  # 物品積載装置
        
        # 21条: 車枠及び車体
        self.frame_body = ""  # 車枠及び車体


def load_japanese_font():
    """日本語フォントを読み込む"""
    if not _REPORTLAB_AVAILABLE:
        return 'Helvetica'
    
    font_paths = [
        'C:/Windows/Fonts/msgothic.ttc',
        'C:/Windows/Fonts/meiryo.ttc',
        'C:/Windows/Fonts/yugothic.ttf',
        'ipaexg.ttf',
        'ipaexm.ttf',
        'fonts/ipaexg.ttf',
        'fonts/ipaexm.ttf'
    ]
    
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont('JPFont', font_path))
                return 'JPFont'
            except Exception:
                continue
    return 'Helvetica'


def collect_calculation_data(panels: list) -> dict:
    """
    全パネルから計算結果と入力値を収集して統合する
    
    Args:
        panels: [(title, panel), ...] のリスト
    
    Returns:
        統合された計算データと入力値の辞書
    """
    collected = {}
    
    for title, panel in panels:
        if not hasattr(panel, 'get_state'):
            continue
        
        try:
            state = panel.get_state()
            
            # パネルタイプごとにデータを収集
            if '重量計算' in title:
                if 'last_data' in state and state['last_data']:
                    collected['weight'] = state['last_data']
                # 入力値も保存
                input_data = {}
                for key in state:
                    if key not in ('last_data',):
                        input_data[key] = state[key]
                collected['weight_inputs'] = input_data
            
            elif '車体計算' in title or 'カーブ' in title:
                if 'last_values' in state and state['last_values']:
                    collected['car'] = state['last_values']
                # 入力値も保存
                input_data = {}
                for key in state:
                    if key not in ('last_values',):
                        input_data[key] = state[key]
                collected['car_inputs'] = input_data
            
            elif '連結仕様' in title:
                if 'last_values' in state and state['last_values']:
                    collected['trailer_spec_result'] = state['last_values']
                # 入力値も保存
                input_data = {}
                for key in state:
                    if key not in ('last_values',):
                        input_data[key] = state[key]
                collected['trailer_spec_inputs'] = input_data
            
            elif 'トレーラ諸元' in title or 'ライト・トレーラ' in title:
                # 入力値を取得
                input_data = {}
                for key in state:
                    input_data[key] = state.get(key, '')
                collected['trailer_spec'] = input_data
            
            elif '安定角' in title:
                if 'last' in state:
                    collected['stability'] = state['last']
                input_data = {}
                for key in state:
                    if key not in ('last',):
                        input_data[key] = state[key]
                collected['stability_inputs'] = input_data
            
            elif '車枠強度' in title:
                if 'last' in state:
                    collected['frame_strength'] = state['last']
            
            elif '車軸強度' in title:
                if 'last' in state:
                    collected['axle_strength'] = state['last']
                input_data = {}
                for key in state:
                    if key not in ('last',):
                        input_data[key] = state[key]
                collected['axle_strength_inputs'] = input_data
            
            elif '旋回半径' in title:
                input_data = {}
                for key in state:
                    input_data[key] = state.get(key, '')
                collected['turning'] = input_data
        
        except Exception as e:
            print(f"Warning: Failed to collect data from {title}: {e}")
    
    return collected


def auto_fill_form1_data(collected: dict) -> Form1Data:
    """
    収集した計算データから第1号様式のデータを自動生成
    
    Args:
        collected: collect_calculation_data()の戻り値
    
    Returns:
        Form1Data インスタンス
    """
    data = Form1Data()
    
    # トレーラ諸元から基本情報を取得
    if 'trailer_spec' in collected:
        spec = collected['trailer_spec']
        # 寸法情報を取得
        if 'trailer_length' in spec:
            length_val = spec.get('trailer_length', '')
            try:
                length_num = float(str(length_val).strip()) if length_val else 0
                data.length = str(int(length_num)) if length_num else ""
            except (ValueError, TypeError):
                pass
        if 'trailer_width' in spec:
            width_val = spec.get('trailer_width', '')
            try:
                width_num = float(str(width_val).strip()) if width_val else 0
                data.width = str(int(width_num)) if width_num else ""
            except (ValueError, TypeError):
                pass
        if 'trailer_height' in spec:
            height_val = spec.get('trailer_height', '')
            try:
                height_num = float(str(height_val).strip()) if height_val else 0
                data.height = str(int(height_num)) if height_num else ""
            except (ValueError, TypeError):
                pass
        if 'trailer_wheelbase' in spec:
            wheelbase_val = spec.get('trailer_wheelbase', '')
            try:
                wheelbase_num = float(str(wheelbase_val).strip()) if wheelbase_val else 0
                data.wheelbase = str(int(wheelbase_num)) if wheelbase_num else ""
            except (ValueError, TypeError):
                pass
        # 古い形式もサポート（L, W, H）
        if not data.length and 'L' in spec:
            data.length = str(int(float(spec.get('L', 0))))
        if not data.width and 'W' in spec:
            data.width = str(int(float(spec.get('W', 0))))
        if not data.height and 'H' in spec:
            data.height = str(int(float(spec.get('H', 0))))
        if not data.wheelbase and 'wheelbase' in spec:
            data.wheelbase = str(int(float(spec.get('wheelbase', 0))))
        if 'tread' in spec:
            data.tread_front = str(int(float(spec.get('tread', 0))))
            data.tread_rear = str(int(float(spec.get('tread', 0))))
        # トレッド（前・後）
        if 'trailer_tread_front' in spec:
            tread_f_val = spec.get('trailer_tread_front', '')
            try:
                tread_f_num = float(str(tread_f_val).strip()) if tread_f_val else 0
                data.tread_front = str(int(tread_f_num)) if tread_f_num else ""
            except (ValueError, TypeError):
                pass
        if 'trailer_tread_rear' in spec:
            tread_r_val = spec.get('trailer_tread_rear', '')
            try:
                tread_r_num = float(str(tread_r_val).strip()) if tread_r_val else 0
                data.tread_rear = str(int(tread_r_num)) if tread_r_num else ""
            except (ValueError, TypeError):
                pass
        # オーバーハング（前・後）
        if 'trailer_overhang_front' in spec:
            over_f_val = spec.get('trailer_overhang_front', '')
            try:
                over_f_num = float(str(over_f_val).strip()) if over_f_val else 0
                data.overhang_front = str(int(over_f_num)) if over_f_num else ""
            except (ValueError, TypeError):
                pass
        if 'trailer_overhang_rear' in spec:
            over_r_val = spec.get('trailer_overhang_rear', '')
            try:
                over_r_num = float(str(over_r_val).strip()) if over_r_val else 0
                data.overhang_rear = str(int(over_r_num)) if over_r_num else ""
            except (ValueError, TypeError):
                pass
    
    # トレーラ諸元入力値からも取得
    if 'trailer_spec_inputs' in collected:
        spec_inputs = collected['trailer_spec_inputs']
        if not data.length and 'L' in spec_inputs:
            data.length = str(spec_inputs.get('L', ''))
        if not data.width and 'W' in spec_inputs:
            data.width = str(spec_inputs.get('W', ''))
        if not data.height and 'H' in spec_inputs:
            data.height = str(spec_inputs.get('H', ''))
    
    # 重量計算から重量情報を取得
    if 'weight' in collected:
        weight = collected['weight']
        total_w = weight.get('total_weight', 0)
        data.vehicle_total_weight = str(int(total_w)) if total_w else ""
        # 前軸・後軸重量
        if 'front_axle_weight' in weight:
            data.axle_weight_front = str(int(weight.get('front_axle_weight', 0)))
        if 'rear_axle_weight' in weight:
            data.axle_weight_rear = str(int(weight.get('rear_axle_weight', 0)))
    
    # 重量計算入力値からも取得
    if 'weight_inputs' in collected:
        weight_inputs = collected['weight_inputs']
        # 車両重量（車体重量のみ）
        if not data.vehicle_weight and 'vw' in weight_inputs:
            vw_val = weight_inputs.get('vw', '')
            try:
                vw_num = float(str(vw_val).strip()) if vw_val else 0
                data.vehicle_weight = str(int(vw_num)) if vw_num else ""
            except (ValueError, TypeError):
                pass
        # 最大積載量
        if not data.max_load_weight and 'ml' in weight_inputs:
            ml_val = weight_inputs.get('ml', '')
            try:
                ml_num = float(str(ml_val).strip()) if ml_val else 0
                data.max_load_weight = str(int(ml_num)) if ml_num else ""
            except (ValueError, TypeError):
                pass
        # 車両総重量（vw + ml）
        if not data.vehicle_total_weight and 'vw' in weight_inputs and 'ml' in weight_inputs:
            try:
                vw = float(str(weight_inputs.get('vw', 0)).strip()) if weight_inputs.get('vw') else 0
                ml = float(str(weight_inputs.get('ml', 0)).strip()) if weight_inputs.get('ml') else 0
                if vw and ml:
                    data.vehicle_total_weight = str(int(vw + ml))
            except (ValueError, TypeError):
                pass
        # 前軸・後軸重量
        if 'fa' in weight_inputs:
            fa_val = weight_inputs.get('fa', '')
            try:
                fa_num = float(str(fa_val).strip()) if fa_val else 0
                data.axle_weight_front = str(int(fa_num)) if fa_num else ""
            except (ValueError, TypeError):
                pass
        if 'ra' in weight_inputs:
            ra_val = weight_inputs.get('ra', '')
            try:
                ra_num = float(str(ra_val).strip()) if ra_val else 0
                data.axle_weight_rear = str(int(ra_num)) if ra_num else ""
            except (ValueError, TypeError):
                pass
    
    # 車軸数を推定（車軸強度計算から）
    if 'axle_strength' in collected:
        axle = collected['axle_strength']
        if 'axle_count' in axle:
            data.axle_count = str(axle['axle_count'])
        else:
            data.axle_count = "2"  # デフォルト
    
    # 車軸強度入力値からも取得
    if 'axle_strength_inputs' in collected and not data.axle_count:
        axle_inputs = collected['axle_strength_inputs']
        if 'axle_count' in axle_inputs:
            data.axle_count = str(axle_inputs.get('axle_count', ''))
    
    # 車両タイプの設定
    data.vehicle_type = "組立車（トレーラ）"
    
    return data


def auto_fill_form2_data(collected: dict) -> Form2Data:
    """
    収集した計算データから保安基準適合検討表のデータを自動生成
    
    Args:
        collected: collect_calculation_data()の戻り値
    
    Returns:
        Form2Data インスタンス
    """
    data = Form2Data()
    
    # 2条: 寸法 - トレーラ諸元から取得
    if 'trailer_spec' in collected:
        spec = collected['trailer_spec']
        if 'trailer_length' in spec or 'L' in spec:
            length_val = spec.get('trailer_length', spec.get('L', ''))
            try:
                length_num = float(str(length_val).strip()) if length_val else 0
                data.length = str(int(length_num)) if length_num else ""
            except (ValueError, TypeError):
                pass
        if 'trailer_width' in spec or 'W' in spec:
            width_val = spec.get('trailer_width', spec.get('W', ''))
            try:
                width_num = float(str(width_val).strip()) if width_val else 0
                data.width = str(int(width_num)) if width_num else ""
            except (ValueError, TypeError):
                pass
        if 'trailer_height' in spec or 'H' in spec:
            height_val = spec.get('trailer_height', spec.get('H', ''))
            try:
                height_num = float(str(height_val).strip()) if height_val else 0
                data.height = str(int(height_num)) if height_num else ""
            except (ValueError, TypeError):
                pass
    
    # 3条: 最低地上高（デフォルト値を設定）
    data.ground_clearance = "100"  # 一般的なライトトレーラの最低地上高
    
    # 3条の2: 車台及び車体
    data.chassis_structure = "鋼製フレーム構造"
    
    # 4条の2: 牽引 - 重量計算から取得
    if 'weight' in collected:
        weight = collected['weight']
        if 'total_weight' in weight:
            data.trailer_weight = str(int(weight.get('total_weight', 0)))
    if 'weight_inputs' in collected:
        weight_inputs = collected['weight_inputs']
        if not data.trailer_weight and 'vw' in weight_inputs:
            try:
                vw_num = float(str(weight_inputs.get('vw', 0)).strip()) if weight_inputs.get('vw') else 0
                data.trailer_weight = str(int(vw_num)) if vw_num else ""
            except (ValueError, TypeError):
                pass
    data.coupler_type = "ボールカプラー"
    
    # 5条: 重量等
    if 'weight_inputs' in collected:
        weight_inputs = collected['weight_inputs']
        if 'vw' in weight_inputs:
            try:
                vw_num = float(str(weight_inputs.get('vw', 0)).strip()) if weight_inputs.get('vw') else 0
                data.vehicle_weight = str(int(vw_num)) if vw_num else ""
            except (ValueError, TypeError):
                pass
        if 'ml' in weight_inputs:
            try:
                ml_num = float(str(weight_inputs.get('ml', 0)).strip()) if weight_inputs.get('ml') else 0
                data.max_load_weight = str(int(ml_num)) if ml_num else ""
            except (ValueError, TypeError):
                pass
        if 'fa' in weight_inputs:
            try:
                fa_num = float(str(weight_inputs.get('fa', 0)).strip()) if weight_inputs.get('fa') else 0
                data.axle_weight_front = str(int(fa_num)) if fa_num else ""
            except (ValueError, TypeError):
                pass
        if 'ra' in weight_inputs:
            try:
                ra_num = float(str(weight_inputs.get('ra', 0)).strip()) if weight_inputs.get('ra') else 0
                data.axle_weight_rear = str(int(ra_num)) if ra_num else ""
            except (ValueError, TypeError):
                pass
        # 最大積載量含む総重量（vw + ml）
        if not data.max_total_weight and 'vw' in weight_inputs and 'ml' in weight_inputs:
            try:
                vw = float(str(weight_inputs.get('vw', 0)).strip()) if weight_inputs.get('vw') else 0
                ml = float(str(weight_inputs.get('ml', 0)).strip()) if weight_inputs.get('ml') else 0
                if vw and ml:
                    data.max_total_weight = str(int(vw + ml))
            except (ValueError, TypeError):
                pass
        # 前軸・後軸重量
        if 'fa' in weight_inputs:
            fa_val = weight_inputs.get('fa', '')
            try:
                fa_num = float(str(fa_val).strip()) if fa_val else 0
                data.axle_weight_front = str(int(fa_num)) if fa_num else ""
            except (ValueError, TypeError):
                pass
        if 'ra' in weight_inputs:
            ra_val = weight_inputs.get('ra', '')
            try:
                ra_num = float(str(ra_val).strip()) if ra_val else 0
                data.axle_weight_rear = str(int(ra_num)) if ra_num else ""
            except (ValueError, TypeError):
                pass
    
    # 6条以降: デフォルト値を設定（ライトトレーラの一般的な仕様）
    data.tire_condition = "適合"
    data.has_engine = "無し"
    data.fuel_system = "該当なし"
    data.lubrication_system = "該当なし"
    data.exhaust_system = "該当なし"
    data.emission_control = "該当なし"
    data.noise_control = "該当なし"
    data.noise_performance = "該当なし"
    data.proximity_noise = "該当なし"
    data.parking_brake = "適合"
    data.service_brake = "トレーラブレーキ付き"
    data.suspension = "リーフスプリング式"
    data.fuel_tank = "該当なし"
    data.steering = "該当なし（被牽引車）"
    data.lock_device = "該当なし"
    data.coupling_device = "ボールカプラー式"
    data.safety_chain = "安全チェーン取付済み"
    data.seating = "なし"
    data.standing_space = "なし"
    data.cargo_device = "荷台付き"
    data.frame_body = "鋼製フレーム・鋼板製荷台"
    
    return data


def generate_form1_pdf(data: Form1Data, output_path: str, template_path: Optional[str] = None):
    """
    第1号様式PDFを生成
    
    Args:
        data: Form1Data インスタンス
        output_path: 出力PDFのパス
        template_path: テンプレートPDFのパス（オプション）
    """
    if not _REPORTLAB_AVAILABLE:
        raise ImportError("ReportLabがインストールされていません")
    
    # テンプレートがある場合はオーバーレイ方式、ない場合は新規作成
    if template_path and os.path.exists(template_path) and _PYPDF2_AVAILABLE:
        _generate_with_template(data, output_path, template_path)
    else:
        _generate_without_template(data, output_path)


def _generate_without_template(data: Form1Data, output_path: str):
    """テンプレートなしで第1号様式PDFを生成"""
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    
    # フォント設定
    font = load_japanese_font()
    
    # タイトル
    c.setFont(font, 16)
    c.drawCentredString(width / 2, height - 50, "第1号様式")
    c.setFont(font, 14)
    c.drawCentredString(width / 2, height - 75, "組立車等届出書")
    
    # 本文開始位置
    y = height - 120
    line_height = 20
    left_margin = 60
    label_width = 150
    
    c.setFont(font, 11)
    
    # 申請者情報
    items = [
        ("申請日", data.application_date),
        ("氏名又は名称", data.applicant_name),
        ("住所", data.applicant_address),
        ("", ""),
        ("自動車の種別", data.vehicle_type),
        ("自動車の名称", data.vehicle_name),
        ("型式", data.vehicle_model),
        ("", ""),
        ("【寸法】", ""),
        ("長さ", f"{data.length} mm" if data.length else ""),
        ("幅", f"{data.width} mm" if data.width else ""),
        ("高さ", f"{data.height} mm" if data.height else ""),
        ("ホイールベース", f"{data.wheelbase} mm" if data.wheelbase else ""),
        ("トレッド（前）", f"{data.tread_front} mm" if data.tread_front else ""),
        ("トレッド（後）", f"{data.tread_rear} mm" if data.tread_rear else ""),
        ("", ""),
        ("【重量】", ""),
        ("車両重量", f"{data.vehicle_weight} kg" if data.vehicle_weight else ""),
        ("車両総重量", f"{data.vehicle_total_weight} kg" if data.vehicle_total_weight else ""),
        ("前軸重", f"{data.axle_weight_front} kg" if data.axle_weight_front else ""),
        ("後軸重", f"{data.axle_weight_rear} kg" if data.axle_weight_rear else ""),
        ("車軸数", data.axle_count if data.axle_count else ""),
        ("", ""),
        ("備考", data.notes),
    ]
    
    for label, value in items:
        if label == "":
            y -= line_height / 2
            continue
        
        if label.startswith("【"):
            c.setFont(font, 12)
            c.drawString(left_margin, y, label)
            c.setFont(font, 11)
        else:
            c.drawString(left_margin, y, f"{label}:")
            c.drawString(left_margin + label_width, y, value)
        
        y -= line_height
        
        if y < 80:
            c.showPage()
            c.setFont(font, 11)
            y = height - 60
    
    c.save()


def _generate_with_template(data: Form1Data, output_path: str, template_path: str):
    """テンプレートPDFにオーバーレイして第1号様式を生成"""
    # オーバーレイ用の一時PDFを作成
    import tempfile
    fd, overlay_path = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    
    try:
        # オーバーレイPDFの作成
        c = canvas.Canvas(overlay_path, pagesize=A4)
        width, height = A4
        font = load_japanese_font()
        c.setFont(font, 10)
        
        # 座標は実際のフォームに合わせて調整が必要
        # ここでは例として基本的な位置を設定
        if data.applicant_name:
            c.drawString(150, height - 150, data.applicant_name)
        if data.applicant_address:
            c.drawString(150, height - 170, data.applicant_address)
        if data.vehicle_type:
            c.drawString(150, height - 220, data.vehicle_type)
        if data.length:
            c.drawString(200, height - 350, f"{data.length}")
        if data.width:
            c.drawString(200, height - 370, f"{data.width}")
        if data.height:
            c.drawString(200, height - 390, f"{data.height}")
        if data.vehicle_weight:
            c.drawString(200, height - 450, f"{data.vehicle_weight}")
        if data.vehicle_total_weight:
            c.drawString(200, height - 470, f"{data.vehicle_total_weight}")
        
        c.save()
        
        # テンプレートとオーバーレイを結合
        template_pdf = PdfReader(template_path)
        overlay_pdf = PdfReader(overlay_path)
        writer = PdfWriter()
        
        # 最初のページにオーバーレイ
        if len(template_pdf.pages) > 0 and len(overlay_pdf.pages) > 0:
            page = template_pdf.pages[0]
            page.merge_page(overlay_pdf.pages[0])
            writer.add_page(page)
        
        # 残りのページを追加
        for i in range(1, len(template_pdf.pages)):
            writer.add_page(template_pdf.pages[i])
        
        with open(output_path, 'wb') as f:
            writer.write(f)
    
    finally:
        if os.path.exists(overlay_path):
            os.unlink(overlay_path)


class OverviewData:
    """概要等説明書・装置の概要用データクラス"""
    def __init__(self):
        # 基本情報
        self.application_date = ""  # 申請日
        self.applicant_name = ""  # 申請者名
        self.vehicle_name = ""  # 車名
        self.vehicle_type = ""  # 車種
        self.approval_number = ""  # 型式認定番号
        
        # 主要寸法・性能
        self.length = ""  # 長さ (mm)
        self.width = ""  # 幅 (mm)
        self.height = ""  # 高さ (mm)
        self.wheelbase = ""  # ホイールベース (mm)
        self.tread_front = ""  # トレッド前 (mm)
        self.tread_rear = ""  # トレッド後 (mm)
        self.vehicle_weight = ""  # 車両重量 (kg)
        self.max_load_weight = ""  # 最大積載量 (kg)
        self.vehicle_total_weight = ""  # 車両総重量 (kg)
        self.max_speed = ""  # 最高速度 (km/h)
        
        # 車軸・タイヤ
        self.axle_count = ""  # 車軸数
        self.front_axle_weight = ""  # 前軸重 (kg)
        self.rear_axle_weight = ""  # 後軸重 (kg)
        self.tire_size_front = ""  # 前輪タイヤサイズ
        self.tire_size_rear = ""  # 後輪タイヤサイズ
        
        # 装置説明
        self.purpose = ""  # 目的
        self.vehicle_type_description = ""  # 車種及び車体
        self.engine_description = ""  # 原動機
        self.transmission_description = ""  # 動力伝達装置
        self.steering_description = ""  # 定行装置
        self.brake_description = ""  # 操舵装置
        self.control_description = ""  # 制動装置
        self.suspension_description = ""  # 緩衝装置
        self.fuel_description = ""  # 燃料装置
        self.exhaust_description = ""  # 定気装置
        
        # その他
        self.notes = ""  # 特記事項


def auto_fill_overview_data(collected: dict) -> OverviewData:
    """
    収集した計算データから概要等説明書のデータを自動生成
    
    Args:
        collected: collect_calculation_data()の戻り値
    
    Returns:
        OverviewData インスタンス
    """
    data = OverviewData()
    
    # トレーラ諸元から基本情報を取得
    if 'trailer_spec' in collected:
        spec = collected['trailer_spec']
        # 寸法情報を取得
        if 'trailer_length' in spec:
            length_val = spec.get('trailer_length', '')
            try:
                length_num = float(str(length_val).strip()) if length_val else 0
                data.length = str(int(length_num)) if length_num else ""
            except (ValueError, TypeError):
                pass
        if 'trailer_width' in spec:
            width_val = spec.get('trailer_width', '')
            try:
                width_num = float(str(width_val).strip()) if width_val else 0
                data.width = str(int(width_num)) if width_num else ""
            except (ValueError, TypeError):
                pass
        if 'trailer_height' in spec:
            height_val = spec.get('trailer_height', '')
            try:
                height_num = float(str(height_val).strip()) if height_val else 0
                data.height = str(int(height_num)) if height_num else ""
            except (ValueError, TypeError):
                pass
        if 'trailer_wheelbase' in spec:
            wheelbase_val = spec.get('trailer_wheelbase', '')
            try:
                wheelbase_num = float(str(wheelbase_val).strip()) if wheelbase_val else 0
                data.wheelbase = str(int(wheelbase_num)) if wheelbase_num else ""
            except (ValueError, TypeError):
                pass
        # 古い形式もサポート（L, W, H）
        if not data.length and 'L' in spec:
            data.length = str(int(float(spec.get('L', 0))))
        if not data.width and 'W' in spec:
            data.width = str(int(float(spec.get('W', 0))))
        if not data.height and 'H' in spec:
            data.height = str(int(float(spec.get('H', 0))))
        if not data.wheelbase and 'wheelbase' in spec:
            data.wheelbase = str(int(float(spec.get('wheelbase', 0))))
        if 'tread' in spec:
            data.tread_front = str(int(float(spec.get('tread', 0))))
            data.tread_rear = str(int(float(spec.get('tread', 0))))
        # トレッド（前・後）
        if 'trailer_tread_front' in spec:
            tread_f_val = spec.get('trailer_tread_front', '')
            try:
                tread_f_num = float(str(tread_f_val).strip()) if tread_f_val else 0
                data.tread_front = str(int(tread_f_num)) if tread_f_num else ""
            except (ValueError, TypeError):
                pass
        if 'trailer_tread_rear' in spec:
            tread_r_val = spec.get('trailer_tread_rear', '')
            try:
                tread_r_num = float(str(tread_r_val).strip()) if tread_r_val else 0
                data.tread_rear = str(int(tread_r_num)) if tread_r_num else ""
            except (ValueError, TypeError):
                pass
    
    # 重量計算から重量情報を取得
    if 'weight' in collected:
        weight = collected['weight']
        total_w = weight.get('total_weight', 0)
        data.vehicle_total_weight = str(int(total_w)) if total_w else ""
        if 'front_axle_weight' in weight:
            data.front_axle_weight = str(int(weight.get('front_axle_weight', 0)))
        if 'rear_axle_weight' in weight:
            data.rear_axle_weight = str(int(weight.get('rear_axle_weight', 0)))
    
    # 重量計算入力値からも取得
    if 'weight_inputs' in collected:
        weight_inputs = collected['weight_inputs']
        # 車両重量（車体重量のみ）
        if not data.vehicle_weight and 'vw' in weight_inputs:
            vw_val = weight_inputs.get('vw', '')
            try:
                vw_num = float(str(vw_val).strip()) if vw_val else 0
                data.vehicle_weight = str(int(vw_num)) if vw_num else ""
            except (ValueError, TypeError):
                pass
        # 最大積載量
        if 'ml' in weight_inputs:
            ml_val = weight_inputs.get('ml', '')
            try:
                ml_num = float(str(ml_val).strip()) if ml_val else 0
                data.max_load_weight = str(int(ml_num)) if ml_num else ""
            except (ValueError, TypeError):
                pass
        # 車両総重量（vw + ml）
        if not data.vehicle_total_weight and 'vw' in weight_inputs and 'ml' in weight_inputs:
            try:
                vw = float(str(weight_inputs.get('vw', 0)).strip()) if weight_inputs.get('vw') else 0
                ml = float(str(weight_inputs.get('ml', 0)).strip()) if weight_inputs.get('ml') else 0
                if vw and ml:
                    data.vehicle_total_weight = str(int(vw + ml))
            except (ValueError, TypeError):
                pass
        # 前軸・後軸重量
        if not data.front_axle_weight and 'fa' in weight_inputs:
            fa_val = weight_inputs.get('fa', '')
            try:
                fa_num = float(str(fa_val).strip()) if fa_val else 0
                data.front_axle_weight = str(int(fa_num)) if fa_num else ""
            except (ValueError, TypeError):
                pass
        if not data.rear_axle_weight and 'ra' in weight_inputs:
            ra_val = weight_inputs.get('ra', '')
            try:
                ra_num = float(str(ra_val).strip()) if ra_val else 0
                data.rear_axle_weight = str(int(ra_num)) if ra_num else ""
            except (ValueError, TypeError):
                pass
        # タイヤサイズ
        if not data.tire_size_front and 'ts_front' in weight_inputs:
            tire_f_val = weight_inputs.get('ts_front', '')
            if tire_f_val:
                data.tire_size_front = str(tire_f_val).strip()
        if not data.tire_size_rear and 'ts_rear' in weight_inputs:
            tire_r_val = weight_inputs.get('ts_rear', '')
            if tire_r_val:
                data.tire_size_rear = str(tire_r_val).strip()
    
    # 車軸数を推定（車軸強度計算から）
    if 'axle_strength' in collected:
        axle = collected['axle_strength']
        if 'axle_count' in axle:
            data.axle_count = str(axle['axle_count'])
        else:
            data.axle_count = "2"  # デフォルト
    
    # 車軸強度入力値からも取得
    if 'axle_strength_inputs' in collected and not data.axle_count:
        axle_inputs = collected['axle_strength_inputs']
        if 'axle_count' in axle_inputs:
            data.axle_count = str(axle_inputs.get('axle_count', ''))
    
    # トレーラ諸元入力値からも取得（フォールバック）
    if 'trailer_spec_inputs' in collected:
        spec_inputs = collected['trailer_spec_inputs']
        if not data.length and 'trailer_length' in spec_inputs:
            length_val = spec_inputs.get('trailer_length', '')
            try:
                length_num = float(str(length_val).strip()) if length_val else 0
                data.length = str(int(length_num)) if length_num else ""
            except (ValueError, TypeError):
                pass
        if not data.width and 'trailer_width' in spec_inputs:
            width_val = spec_inputs.get('trailer_width', '')
            try:
                width_num = float(str(width_val).strip()) if width_val else 0
                data.width = str(int(width_num)) if width_num else ""
            except (ValueError, TypeError):
                pass
        if not data.height and 'trailer_height' in spec_inputs:
            height_val = spec_inputs.get('trailer_height', '')
            try:
                height_num = float(str(height_val).strip()) if height_val else 0
                data.height = str(int(height_num)) if height_num else ""
            except (ValueError, TypeError):
                pass
        if not data.wheelbase and 'trailer_wheelbase' in spec_inputs:
            wheelbase_val = spec_inputs.get('trailer_wheelbase', '')
            try:
                wheelbase_num = float(str(wheelbase_val).strip()) if wheelbase_val else 0
                data.wheelbase = str(int(wheelbase_num)) if wheelbase_num else ""
            except (ValueError, TypeError):
                pass
        if not data.tread_front and 'trailer_tread_front' in spec_inputs:
            tread_f_val = spec_inputs.get('trailer_tread_front', '')
            try:
                tread_f_num = float(str(tread_f_val).strip()) if tread_f_val else 0
                data.tread_front = str(int(tread_f_num)) if tread_f_num else ""
            except (ValueError, TypeError):
                pass
        if not data.tread_rear and 'trailer_tread_rear' in spec_inputs:
            tread_r_val = spec_inputs.get('trailer_tread_rear', '')
            try:
                tread_r_num = float(str(tread_r_val).strip()) if tread_r_val else 0
                data.tread_rear = str(int(tread_r_num)) if tread_r_num else ""
            except (ValueError, TypeError):
                pass
    
    # 車両タイプの設定
    data.vehicle_type = "トレーラー"
    data.purpose = "貨物運送用トレーラー"
    
    return data


def generate_overview_pdf(data: OverviewData, output_path: str, template_path: Optional[str] = None):
    """
    概要等説明書PDFを生成
    
    Args:
        data: OverviewData インスタンス
        output_path: 出力PDFのパス
        template_path: テンプレートPDFのパス（オプション）
    """
    if not _REPORTLAB_AVAILABLE:
        raise ImportError("ReportLabがインストールされていません")
    
    # テンプレートがある場合はオーバーレイ方式、ない場合は新規作成
    if template_path and os.path.exists(template_path) and _PYPDF2_AVAILABLE:
        _generate_overview_with_template(data, output_path, template_path)
    else:
        _generate_overview_without_template(data, output_path)


def _generate_overview_without_template(data: OverviewData, output_path: str):
    """テンプレートなしで概要等説明書PDFを生成"""
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    
    # フォント設定
    font = load_japanese_font()
    
    # ページ1: 概要等説明書
    c.setFont(font, 14)
    c.drawCentredString(width / 2, height - 40, "概要等説明書")
    c.setFont(font, 10)
    c.drawString(40, height - 70, f"申請日: {data.application_date}")
    c.drawString(40, height - 90, f"申請者: {data.applicant_name}")
    
    y = height - 120
    line_height = 20
    
    sections = [
        ("基本情報", [
            ("車名", data.vehicle_name),
            ("車種", data.vehicle_type),
            ("型式認定番号", data.approval_number),
        ]),
        ("寸法 (mm)", [
            ("長さ", data.length),
            ("幅", data.width),
            ("高さ", data.height),
            ("ホイールベース", data.wheelbase),
            ("トレッド（前）", data.tread_front),
            ("トレッド（後）", data.tread_rear),
        ]),
        ("重量 (kg)", [
            ("車両重量", data.vehicle_weight),
            ("車両総重量", data.vehicle_total_weight),
            ("最大積載量", data.max_load_weight),
            ("前軸重", data.front_axle_weight),
            ("後軸重", data.rear_axle_weight),
        ]),
        ("性能", [
            ("最高速度", data.max_speed),
            ("車軸数", data.axle_count),
            ("前輪タイヤ", data.tire_size_front),
            ("後輪タイヤ", data.tire_size_rear),
        ]),
    ]
    
    for section_title, items in sections:
        c.setFont(font, 11)
        c.drawString(40, y, section_title)
        y -= line_height
        c.setFont(font, 10)
        
        for label, value in items:
            if value:
                c.drawString(50, y, f"{label}: {value}")
                y -= line_height
        
        y -= line_height / 2
        if y < 100:
            c.showPage()
            c.setFont(font, 10)
            y = height - 40
    
    # ページ2: 装置の概要
    c.showPage()
    c.setFont(font, 14)
    c.drawCentredString(width / 2, height - 40, "装置の概要")
    
    y = height - 80
    c.setFont(font, 10)
    
    descriptions = [
        ("目的", data.purpose),
        ("車種及び車体", data.vehicle_type_description),
        ("原動機", data.engine_description),
        ("動力伝達装置", data.transmission_description),
        ("定行装置", data.steering_description),
        ("操舵装置", data.brake_description),
        ("制動装置", data.control_description),
        ("緩衝装置", data.suspension_description),
        ("燃料装置", data.fuel_description),
        ("定気装置", data.exhaust_description),
    ]
    
    for label, value in descriptions:
        c.setFont(font, 10)
        c.drawString(40, y, f"{label}:")
        y -= line_height
        if value:
            c.setFont(font, 9)
            # テキストをラップして描画
            lines = value.split('\n') if value else [""]
            for line in lines:
                c.drawString(50, y, line)
                y -= line_height
        y -= line_height / 2
        
        if y < 100:
            c.showPage()
            c.setFont(font, 10)
            y = height - 40
    
    c.save()


def _generate_overview_with_template(data: OverviewData, output_path: str, template_path: str):
    """テンプレートPDFにオーバーレイして概要等説明書を生成"""
    import tempfile
    fd, overlay_path = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    
    try:
        # オーバーレイPDFの作成
        c = canvas.Canvas(overlay_path, pagesize=A4)
        width, height = A4
        font = load_japanese_font()
        c.setFont(font, 10)
        
        # ページ1にデータを記入（座標は実際のフォームに合わせて調整が必要）
        if data.application_date:
            c.drawString(450, height - 110, data.application_date)
        if data.vehicle_name:
            c.drawString(150, height - 180, data.vehicle_name)
        if data.length:
            c.drawString(200, height - 280, data.length)
        if data.width:
            c.drawString(200, height - 300, data.width)
        if data.height:
            c.drawString(200, height - 320, data.height)
        if data.vehicle_weight:
            c.drawString(200, height - 380, data.vehicle_weight)
        if data.vehicle_total_weight:
            c.drawString(200, height - 400, data.vehicle_total_weight)
        
        c.save()
        
        # テンプレートとオーバーレイを結合
        template_pdf = PdfReader(template_path)
        overlay_pdf = PdfReader(overlay_path)
        writer = PdfWriter()
        
        # ページをマージ
        for i in range(len(template_pdf.pages)):
            page = template_pdf.pages[i]
            if i < len(overlay_pdf.pages):
                page.merge_page(overlay_pdf.pages[i])
            writer.add_page(page)
        
        with open(output_path, 'wb') as f:
            writer.write(f)
    
    finally:
        if os.path.exists(overlay_path):
            os.unlink(overlay_path)


def generate_form2_pdf(data: Form2Data, output_path: str):
    """
    保安基準適合検討表（ライトトレーラ用）PDFを生成
    
    Args:
        data: Form2Data インスタンス
        output_path: 出力PDFのパス
    """
    if not _REPORTLAB_AVAILABLE:
        raise ImportError("ReportLabがインストールされていません")
    
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    
    # フォント設定
    font = load_japanese_font()
    
    # タイトル
    c.setFont(font, 14)
    c.drawCentredString(width / 2, height - 40, "保安基準適合検討表（ライトトレーラ用）")
    
    # 表の設定
    y = height - 80
    left = 40
    col_widths = [30, 60, 230, 160, 40]  # 区条、項目、基準の具体的内容等、適否見込み又は適用理由、備考
    total_width = sum(col_widths)
    row_height = 25
    
    c.setFont(font, 9)
    
    # ヘッダー行
    headers = ["区条", "項目", "基準の具体的内容等", "適否見込み又は適用理由", "備考"]
    x = left
    for i, header in enumerate(headers):
        c.rect(x, y - row_height, col_widths[i], row_height)
        c.drawString(x + 3, y - 15, header)
        x += col_widths[i]
    
    y -= row_height
    
    # データ行を定義
    rows = [
        ("2条", "長さ", f"{data.length} mm以下", f"L = {data.length} mm", ""),
        ("", "幅", f"{data.width} mm以下", f"W = {data.width} mm", ""),
        ("", "高さ", f"{data.height} mm以下", f"H = {data.height} mm", ""),
        ("3条", "最低地上高", "車体下部突出物がないこと", data.ground_clearance + " mm", ""),
        ("3条の2", "車台及び車体", "堅ろうで安全な構造", data.chassis_structure, ""),
        ("4条の2", "牽引", f"最大積載状態で{data.trailer_weight}kg", data.coupler_type, ""),
        ("5条", "重量等", "車両重量の適合", f"{data.vehicle_weight} kg", ""),
        ("", "前軸重", "前軸荷重の適合", f"{data.axle_weight_front} kg", ""),
        ("", "後軸重", "後軸荷重の適合", f"{data.axle_weight_rear} kg", ""),
        ("6条", "走行装置", "タイヤの状態が適合", data.tire_condition, ""),
        ("7条", "原動機", "原動機の有無", data.has_engine, ""),
        ("8条", "燃料装置", "燃料装置の構造", data.fuel_system, ""),
        ("9条", "潤滑装置", "潤滑装置の構造", data.lubrication_system, ""),
        ("10条", "排気管", "排気管の構造", data.exhaust_system, ""),
        ("11条", "排出ガス", "排出ガス発散防止", data.emission_control, ""),
        ("11条の2", "排気騒音", "排気騒音防止装置", data.noise_control, ""),
        ("11条の3", "騒音性能", "騒音防止性能", data.noise_performance, ""),
        ("11条の4", "近接騒音", "近接排気騒音", data.proximity_noise, ""),
        ("12条", "駐車ブレーキ", "駐車ブレーキの性能", data.parking_brake, ""),
        ("", "常用ブレーキ", "制動装置の性能", data.service_brake, ""),
        ("13条", "緩衝装置", "緩衝装置の構造", data.suspension, ""),
        ("14条", "燃料タンク", "燃料タンクの構造", data.fuel_tank, ""),
        ("15条", "操縦装置", "操縦装置（被牽引車）", data.steering, ""),
        ("16条", "施錠装置", "施錠装置", data.lock_device, ""),
        ("17条", "連結装置", "連結装置の構造・強度", data.coupling_device, ""),
        ("17条の2", "安全装置", "安全チェーン等", data.safety_chain, ""),
        ("18条", "乗車装置", "乗車装置", data.seating, ""),
        ("19条", "立席", "立席の有無", data.standing_space, ""),
        ("20条", "積載装置", "物品積載装置", data.cargo_device, ""),
        ("21条", "車枠車体", "車枠及び車体の構造", data.frame_body, ""),
    ]
    
    # 各行を描画
    for row_data in rows:
        x = left
        for i, cell in enumerate(row_data):
            c.rect(x, y - row_height, col_widths[i], row_height)
            # テキストを描画（長い場合は折り返し）
            text = str(cell)
            if len(text) > 30 and i == 2:  # 基準内容欄は折り返し
                lines = [text[j:j+28] for j in range(0, len(text), 28)]
                for k, line in enumerate(lines[:2]):  # 最大2行
                    c.drawString(x + 2, y - 12 - k * 10, line)
            else:
                c.drawString(x + 2, y - 15, text)
            x += col_widths[i]
        y -= row_height
        
        # ページ境界チェック
        if y < 60:
            c.showPage()
            c.setFont(font, 9)
            y = height - 40
    
    c.save()
