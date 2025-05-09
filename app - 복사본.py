from flask import Flask, render_template, request, jsonify, session
import pandas as pd
import os
from werkzeug.security import check_password_hash, generate_password_hash
import re
import math
import random

app = Flask(__name__)
app.secret_key = os.urandom(24)

# CSV 파일 경로
USER_INFO_PATH = 'data/사용자정보_등록현황_20250502.csv'
CONTRACT_INFO_PATH = 'data/위탁업체정보_등록현황_20250502.csv'
SUBCONTRACT_INFO_PATH = 'data/재위탁통보정보_등록현황_20250502.csv'

RECEIVER_COL_IDX = 5
TRUSTOR_COL_IDX = 6
TRUSTEE_COL_IDX = 7

def break_bizname(name):
    name = str(name).strip()
    if len(name) < 7:
        return name

    # 13글자 이상: 3행
    if len(name) >= 13:
        first = name[:7]
        second = name[7:13]
        third = name[13:]
        # 3행에도 '주식회사' 규칙 적용
        if third.startswith('주식회사'):
            third = '주식회사' + third[5:]
        elif third.endswith('주식회사'):
            third = third[:-5] + '\n주식회사'
        return f"{first}\n{second}\n{third}".strip()

    # 7~12글자: 기존 2행 규칙
    # 1. '주식회사'가 맨 앞에 있으면
    if name.startswith('주식회사 '):
        return '주식회사\n' + name[5:].strip()
    # 2. '주식회사'가 맨 뒤에 있으면
    if name.endswith(' 주식회사'):
        return name[:-5].strip() + '\n주식회사'
    # 3. '주식회사'가 중간에 있으면
    if '주식회사' in name and len(name) > 7:
        idx = name.find('주식회사')
        if idx == 0:
            return '주식회사\n' + name[5:].strip()
        elif idx == len(name) - 5:
            return name[:idx].strip() + '\n주식회사'
        else:
            return name[:idx].strip() + '\n주식회사' + name[idx+5:].strip()
    # 4. 띄어쓰기가 있으면 마지막 띄어쓰기에서 줄바꿈
    if ' ' in name:
        idx = name.rfind(' ')
        return name[:idx] + '\n' + name[idx+1:]
    # 5. 띄어쓰기가 없으면 7글자에서 줄바꿈
    return name[:7] + '\n' + name[7:]

def try_read_csv(path, **kwargs):
    for enc in ['utf-8-sig', 'utf-8', 'cp949', 'euc-kr']:
        try:
            return pd.read_csv(path, encoding=enc, **kwargs)
        except Exception as e:
            last_error = e
    raise RuntimeError(f'CSV 파일 인코딩 자동 판별 실패: {path}\n마지막 에러: {last_error}')

def load_data():
    users_df = try_read_csv(USER_INFO_PATH, dtype={'사업자등록번호': str})
    contracts_df = try_read_csv(CONTRACT_INFO_PATH, dtype={'위탁-사업자등록번호': str, '수탁-사업자등록번호': str})
    subcontracts_df = try_read_csv(SUBCONTRACT_INFO_PATH)
    return users_df, contracts_df, subcontracts_df

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    try:
        email = request.form.get('email').strip()
        business_number = str(request.form.get('business_number')).strip()
        
        users_df, _, _ = load_data()
        users_df['Email'] = users_df['Email'].astype(str).str.strip()
        users_df['사업자등록번호'] = users_df['사업자등록번호'].astype(str).str.strip()
        users_df['제약사/CSO구분명'] = users_df['제약사/CSO구분명'].astype(str).str.strip()
        
        print('입력값:', email, business_number)
        print('Email 샘플:', users_df['Email'].head(10).tolist())
        print('사업자등록번호 샘플:', users_df['사업자등록번호'].head(10).tolist())
        
        user = users_df[
            (users_df['Email'] == email) & 
            (users_df['사업자등록번호'] == business_number)
        ]
        
        if len(user) == 0:
            sample = users_df[['Email', '사업자등록번호', '제약사/CSO구분명']].head(10).to_dict()
            return jsonify({'success': False, 'message': f'일치하는 데이터가 없습니다. 입력값: {email}, {business_number}\n샘플: {sample}'})
        
        if user.iloc[0]['제약사/CSO구분명'] == '제약사':
            session['user_id'] = email
            return jsonify({'success': True})
        return jsonify({'success': False, 'message': '로그인에 실패했습니다.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/get_contract_tree')
def get_contract_tree():
    if 'user_id' not in session:
        return jsonify({'error': '로그인이 필요합니다.'})
    
    users_df, contracts_df, subcontracts_df = load_data()
    user_email = session['user_id']
    
    # 현재 사용자의 계약 정보 조회
    user_contracts = contracts_df[contracts_df['이메일'] == user_email]
    
    tree_data = []
    for _, contract in user_contracts.iterrows():
        subcontractor_email = contract['위탁업체이메일']
        subcontractor_info = users_df[users_df['이메일'] == subcontractor_email].iloc[0]
        
        # 하위 계약 정보 조회
        sub_contracts = contracts_df[contracts_df['이메일'] == subcontractor_email]
        reported_subcontracts = subcontracts_df[
            (subcontracts_df['이메일'] == user_email) & 
            (subcontracts_df['위탁업체이메일'] == subcontractor_email)
        ]
        
        node = {
            'id': subcontractor_email,
            'name': subcontractor_info['업체명'],
            'contract_count': len(sub_contracts),
            'reported_count': len(reported_subcontracts),
            'children': []
        }
        
        for _, sub_contract in sub_contracts.iterrows():
            sub_subcontractor_email = sub_contract['위탁업체이메일']
            sub_subcontractor_info = users_df[users_df['이메일'] == sub_subcontractor_email].iloc[0]
            
            sub_reported = subcontracts_df[
                (subcontracts_df['이메일'] == subcontractor_email) & 
                (subcontracts_df['위탁업체이메일'] == sub_subcontractor_email)
            ]
            
            child_node = {
                'id': sub_subcontractor_email,
                'name': sub_subcontractor_info['업체명'],
                'contract_count': len(contracts_df[contracts_df['이메일'] == sub_subcontractor_email]),
                'reported_count': len(sub_reported)
            }
            node['children'].append(child_node)
        
        tree_data.append(node)
    
    return jsonify(tree_data)

def format_biznum(biznum):
    digits = re.sub(r'[^0-9]', '', str(biznum))
    if len(digits) == 10:
        return f'{digits[:3]}-{digits[3:5]}-{digits[5:]}'
    return biznum

@app.route('/get_contract_list')
def get_contract_list():
    try:
        users_df, contracts_df, subcontracts_df = load_data()
        # 컬럼명 정규화
        users_df['사업자등록번호'] = users_df['사업자등록번호'].astype(str).str.strip()
        contracts_df['위탁-사업자등록번호'] = contracts_df['위탁-사업자등록번호'].astype(str).str.strip()
        contracts_df['수탁-사업자등록번호'] = contracts_df['수탁-사업자등록번호'].astype(str).str.strip()
        
        # 재위탁통보정보 컬럼 매핑
        receiver_col = subcontracts_df.columns[5]  # 수신업체-사업자등록번호 (인덱스 5)
        trustor_col = subcontracts_df.columns[6]   # 위탁업체-사업자등록번호 (인덱스 6)
        trustee_col = subcontracts_df.columns[7]   # 수탁업체-사업자등록번호 (인덱스 7)
        
        # 열 데이터 문자열 변환 및 공백 제거
        subcontracts_df[receiver_col] = subcontracts_df[receiver_col].astype(str).str.strip()
        subcontracts_df[trustor_col] = subcontracts_df[trustor_col].astype(str).str.strip()
        subcontracts_df[trustee_col] = subcontracts_df[trustee_col].astype(str).str.strip()

        user_email = session['user_id']
        users_df['Email'] = users_df['Email'].astype(str).str.strip()
        user_row = users_df[users_df['Email'] == user_email]
        if len(user_row) == 0:
            return jsonify({'error': '사용자 정보를 찾을 수 없습니다.'})
        if user_row.iloc[0]['제약사/CSO구분명'] != '제약사':
            return jsonify({'error': '제약사만 접근 가능합니다.'})
        my_bn = str(user_row.iloc[0]['사업자등록번호']).strip()

        # 1차: 위탁업체정보에서 추출
        contracts = contracts_df[contracts_df['위탁-사업자등록번호'] == my_bn]
        trustee_bns = contracts['수탁-사업자등록번호'].tolist()
        trustee_bns = [str(bn).strip() for bn in trustee_bns if pd.notna(bn)]
        trustee_bns = list(dict.fromkeys(trustee_bns))  # 중복 제거
        filtered_users = users_df[users_df['사업자등록번호'].isin(trustee_bns)]

        # 2차(재위탁)부터: 재위탁통보정보에서 하위 업체 수 계산
        sub_counts = {}
        for biznum in trustee_bns:
            # 재위탁통보정보에서 수신업체가 로그인한 제약사이고, 위탁업체가 biznum인 경우의 
            # 중복 제거된 수탁업체 수를 반환
            count = subcontracts_df[
                (subcontracts_df[receiver_col] == my_bn) &
                (subcontracts_df[trustor_col] == biznum)
            ][trustee_col].nunique()
            
            sub_counts[biznum] = count

        result = []
        for _, row in filtered_users.iterrows():
            biznum = row['사업자등록번호']
            trustee_data = {
                '사업자명': row['사업자명'],
                '사업자등록번호': format_biznum(biznum),
                '대표자명': row['대표자명'],
                '사업장소재지': row['사업장소재지'],
                'CSO신고번호': row['CSO신고번호'],
                '재위탁업체': sub_counts.get(biznum, 0),
                '원본사업자등록번호': biznum,
            }
            result.append(trustee_data)
        return jsonify(result)
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': str(e)})


@app.route('/get_subcontract_list', methods=['POST'])
def get_subcontract_list():
    try:
        users_df, contracts_df, subcontracts_df = load_data()
        users_df['사업자등록번호'] = users_df['사업자등록번호'].astype(str).str.strip()
        users_df['Email'] = users_df['Email'].astype(str).str.strip()

        user_email = session['user_id']
        user_row = users_df[users_df['Email'] == user_email]
        if len(user_row) == 0:
            return jsonify({'error': '사용자 정보를 찾을 수 없습니다.'})

        my_bn = str(user_row.iloc[0]['사업자등록번호']).strip()
        parent_biznum = request.json.get('parent_biznum')
        parent_x = request.json.get('parent_x', 0)
        parent_y = request.json.get('parent_y', 0)

        # 재위탁통보정보 컬럼 매핑
        receiver_col = subcontracts_df.columns[5]  # 수신업체-사업자등록번호 (인덱스 5)
        trustor_col = subcontracts_df.columns[6]   # 위탁업체-사업자등록번호 (인덱스 6)
        trustee_col = subcontracts_df.columns[7]   # 수탁업체-사업자등록번호 (인덱스 7)
        
        # 열 데이터 문자열 변환 및 공백 제거
        subcontracts_df[receiver_col] = subcontracts_df[receiver_col].astype(str).str.strip()
        subcontracts_df[trustor_col] = subcontracts_df[trustor_col].astype(str).str.strip()
        subcontracts_df[trustee_col] = subcontracts_df[trustee_col].astype(str).str.strip()

        # 재위탁통보정보에서 하위 업체 찾기
        sub_contracts = subcontracts_df[
            (subcontracts_df[receiver_col] == my_bn) &
            (subcontracts_df[trustor_col] == parent_biznum)
        ]
        
        trustee_bns = sub_contracts[trustee_col].unique()
        filtered_users = users_df[users_df['사업자등록번호'].isin(trustee_bns)]

        result = []
        for _, row in filtered_users.iterrows():
            biznum = row['사업자등록번호']
            trustee_data = {
                '사업자명': row['사업자명'],
                '사업자등록번호': format_biznum(biznum),
                '대표자명': row['대표자명'],
                '사업장소재지': row['사업장소재지'],
                'CSO신고번호': row['CSO신고번호'],
                '원본사업자등록번호': biznum,
            }

            # 하위 재위탁업체 수 계산
            sub_count = subcontracts_df[
                (subcontracts_df[receiver_col] == my_bn) &
                (subcontracts_df[trustor_col] == biznum)
            ][trustee_col].nunique()
            
            trustee_data['재위탁업체'] = sub_count

            # 하위 노드의 x, y 좌표를 parent 기준으로 배치
            angle = 2 * math.pi * random.uniform(0, 1)
            radius = 200  # 임시 반지름
            x = parent_x + radius * math.cos(angle)
            y = parent_y + radius * math.sin(angle)
            trustee_data['x'] = x
            trustee_data['y'] = y

            result.append(trustee_data)
            
        return jsonify(result)
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': str(e)})


@app.route('/get_network_data')
def get_network_data():
    if 'user_id' not in session:
        return jsonify({'error': '로그인이 필요합니다.'})
    try:
        print("=== get_network_data 진입 ===")
        users_df, contracts_df, subcontracts_df = load_data()
        user_email = session['user_id']
        user_row = users_df[users_df['Email'] == user_email]
        if len(user_row) == 0:
            return jsonify({'error': '사용자 정보를 찾을 수 없습니다.'})
        my_bn = str(user_row.iloc[0]['사업자등록번호']).strip()

        # 모든 데이터프레임의 열 이름을 출력하여 디버깅 (개발 중에만 사용)
        print("users_df columns:", list(users_df.columns))
        print("contracts_df columns:", list(contracts_df.columns))
        print("subcontracts_df columns:", list(subcontracts_df.columns))

        # 데이터 전처리 - 사업자등록번호 모두 문자열로 변환 및 공백 제거
        users_df['사업자등록번호'] = users_df['사업자등록번호'].astype(str).str.strip()
        users_df['Email'] = users_df['Email'].astype(str).str.strip()
        contracts_df['위탁-사업자등록번호'] = contracts_df['위탁-사업자등록번호'].astype(str).str.strip()
        contracts_df['수탁-사업자등록번호'] = contracts_df['수탁-사업자등록번호'].astype(str).str.strip()

        # 재위탁통보정보 컬럼명 확인 및 매핑
        # 인코딩 문제로 인해 실제 컬럼명이 깨져있을 수 있으므로 위치로 접근
        receiver_col = subcontracts_df.columns[5]  # 수신업체-사업자등록번호 (인덱스 5)
        trustor_col = subcontracts_df.columns[6]   # 위탁업체-사업자등록번호 (인덱스 6)
        trustee_col = subcontracts_df.columns[7]   # 수탁업체-사업자등록번호 (인덱스 7)
        
        print(f"Using columns: 수신업체={receiver_col}, 위탁업체={trustor_col}, 수탁업체={trustee_col}")
        
        # 열 데이터 문자열 변환 및 공백 제거
        subcontracts_df[receiver_col] = subcontracts_df[receiver_col].astype(str).str.strip()
        subcontracts_df[trustor_col] = subcontracts_df[trustor_col].astype(str).str.strip()
        subcontracts_df[trustee_col] = subcontracts_df[trustee_col].astype(str).str.strip()

        nodes = []
        edges = []
        node_info = {}
        children = {}
        added_nodes = set()  # 이미 추가된 노드 id(사업자등록번호) 추적용

        # 1차 위탁업체 목록 (contracts_df에서 추출)
        first_level = contracts_df[contracts_df['위탁-사업자등록번호'] == my_bn]['수탁-사업자등록번호'].unique()
        first_level = [str(bn).strip() for bn in first_level if pd.notna(bn)]

        # 중앙 제약사 노드
        nodes.append({
            'id': my_bn,
            'label': break_bizname(safe_str(user_row.iloc[0]['사업자명'])),
            'color': '#97C2FC',
            'shape': 'circle',
            'font': {'size': 24, 'multi': True},
            'size': 300,
            'x': 0,
            'y': 0
        })
        added_nodes.add(my_bn)
        node_info[my_bn] = {
            '사업자명': safe_str(user_row.iloc[0]['사업자명']),
            '사업자등록번호': format_biznum(my_bn),
            '대표자명': safe_str(user_row.iloc[0]['대표자명']),
            '사업장소재지': safe_str(user_row.iloc[0]['사업장소재지']),
            'CSO신고번호': safe_str(user_row.iloc[0].get('CSO신고번호', '')),
            '재위탁업체': len(first_level)
        }
        children[my_bn] = first_level

        # 1차 위탁업체 원형 배치 (동적 원 분배)
        n = len(first_level)
        if n == 0:
            return jsonify({'nodes': nodes, 'edges': edges, 'node_info': node_info, 'children': children})

        def get_circle_distribution(n, base=10, growth=1.2):
            counts = []
            remain = n
            c = base
            while remain > 0:
                this_circle = min(int(c), remain)
                counts.append(this_circle)
                remain -= this_circle
                c *= growth
            return counts

        # 1. 제약사 ↔ 위탁업체(1차 자식)
        # 원별 노드수 조절
        circle_counts = get_circle_distribution(n, base=16, growth=1.8)

        # 첫번째/두번째/세번째 원 반지름 조절
        radii = [200 + i*100 for i in range(len(circle_counts))]

        node_idx = 0
        for circle_idx, count in enumerate(circle_counts):
            for i in range(count):
                if node_idx >= n:
                    break
                bn = first_level[node_idx]
                if bn in added_nodes:
                    node_idx += 1
                    continue
                info_row = users_df[users_df['사업자등록번호'] == bn]
                if len(info_row) == 0:
                    node_idx += 1
                    continue
                info = info_row.iloc[0]
                
                # 각 반지름에서 노드별 거리 랜덤 조정
                angle = 2 * math.pi * i / count + random.uniform(-0.05, 0.05)
                radius = radii[circle_idx] + random.uniform(-20, 20)

                x = radius * math.cos(angle)
                y = radius * math.sin(angle)
                receiver_col = subcontracts_df.columns[5]
                trustor_col = subcontracts_df.columns[6]
                trustee_col = subcontracts_df.columns[7]
                subcontracts_df[receiver_col] = subcontracts_df[receiver_col].astype(str).str.strip()
                subcontracts_df[trustor_col] = subcontracts_df[trustor_col].astype(str).str.strip()
                subcontracts_df[trustee_col] = subcontracts_df[trustee_col].astype(str).str.strip()
                sub_count = subcontracts_df[
                    (subcontracts_df[receiver_col] == my_bn) &
                    (subcontracts_df[trustor_col] == bn)
                ][trustee_col].nunique()
                if sub_count == 0:
                    nodes.append({
                        'id': bn,
                        'label': break_bizname(safe_str(info['사업자명'])),
                        'title': safe_str(info['사업자명']),
                        'color': {
                            'background': "#fff6f6",
                            'border': 'rgba(0,0,0,0)'
                        },
                        'borderWidth': 0,
                        'shape': 'circle',
                        'font': {'size': 14, 'multi': True},
                        'size': 10,
                        'x': x,
                        'y': y
                    })
                    added_nodes.add(bn)
                    node_info[bn] = {
                        '사업자명': safe_str(info['사업자명']),
                        '사업자등록번호': format_biznum(bn),
                        '대표자명': safe_str(info['대표자명']),
                        '사업장소재지': safe_str(info['사업장소재지']),
                        'CSO신고번호': safe_str(info.get('CSO신고번호', '')),
                        '재위탁업체': sub_count
                    }
                    edges.append({'from': my_bn, 'to': bn})
                    children[bn] = []
                    node_idx += 1
                    continue
                if sub_count > 0:
                    size = get_circle_size(sub_count)
                    nodes.append({
                        'id': bn,
                        'label': break_bizname(safe_str(info['사업자명'])),
                        'title': safe_str(info['사업자명']),
                        'color': '#FFB1B1',
                        'shape': 'circle',
                        'font': {'size': 14, 'multi': True},
                        'size': size if size else 20,
                        'x': x,
                        'y': y
                    })
                    added_nodes.add(bn)
                    node_info[bn] = {
                        '사업자명': safe_str(info['사업자명']),
                        '사업자등록번호': format_biznum(bn),
                        '대표자명': safe_str(info['대표자명']),
                        '사업장소재지': safe_str(info['사업장소재지']),
                        'CSO신고번호': safe_str(info.get('CSO신고번호', '')),
                        '재위탁업체': sub_count
                    }
                    edges.append({'from': my_bn, 'to': bn})
                    children[bn] = []
                node_idx += 1

        return jsonify({
            'nodes': nodes,
            'edges': edges,
            'node_info': node_info,
            'children': children
        })
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': str(e)})

def safe_str(val):
    if pd.isna(val) or val is None:
        return ''
    return str(val)

@app.route('/debug_columns')
def debug_columns():
    users_df, contracts_df, subcontracts_df = load_data()
    return jsonify({
        'users_columns': list(users_df.columns),
        'contracts_columns': list(contracts_df.columns),
        'subcontracts_columns': list(subcontracts_df.columns),
        'subcontracts_sample': subcontracts_df.head(3).to_dict(orient='records')
    })

def get_circle_size(sub_count):
    # 최소 20, 최대 70
    return min(20 + sub_count * 0.35, 70)

@app.route('/get_subnetwork_data', methods=['POST'])
def get_subnetwork_data():
    parent_biznum = request.json['parent_biznum']
    parent_x = request.json.get('parent_x', 0)
    parent_y = request.json.get('parent_y', 0)
    users_df, contracts_df, subcontracts_df = load_data()
    receiver_col = subcontracts_df.columns[5]
    trustor_col = subcontracts_df.columns[6]
    trustee_col = subcontracts_df.columns[7]
    subcontracts_df[receiver_col] = subcontracts_df[receiver_col].astype(str).str.strip()
    subcontracts_df[trustor_col] = subcontracts_df[trustor_col].astype(str).str.strip()
    subcontracts_df[trustee_col] = subcontracts_df[trustee_col].astype(str).str.strip()
    sub_contracts = subcontracts_df[(subcontracts_df[trustor_col] == parent_biznum)]
    trustee_bns = sub_contracts[trustee_col].unique()
    filtered_users = users_df[users_df['사업자등록번호'].isin(trustee_bns)]
    nodes, edges, node_info = [], [], {}
    n = len(filtered_users)

    def get_circle_distribution(n, base=18, growth=2.0):
        counts = []
        remain = n
        c = base
        while remain > 0:
            this_circle = min(int(c), remain)
            counts.append(this_circle)
            remain -= this_circle
            c *= growth
        return counts








    # 2. 위탁업체 ↔ 재위탁업체(2차 자식)
    # 원별 노드수 조절
    circle_counts = get_circle_distribution(n, base=16, growth=1.8)

    # 첫번째/두번째/세번째 원 반지름 조절:
    radii = [180 + i*90 for i in range(len(circle_counts))]

    user_idx = 0
    for circle_idx, count in enumerate(circle_counts):
        for i in range(count):
            if user_idx >= n:
                break
            row = filtered_users.iloc[user_idx]
            sub_bn = row['사업자등록번호']

            # 각 반지름에서 노드별 거리 랜덤 조정정
            angle = 2 * math.pi * i / count + random.uniform(-0.05, 0.05)
            radius = radii[circle_idx] + random.uniform(-10, 10)


            x = parent_x + radius * math.cos(angle)
            y = parent_y + radius * math.sin(angle)
            sub_count = subcontracts_df[(subcontracts_df[trustor_col] == sub_bn)][trustee_col].nunique()
            size = get_circle_size(sub_count)
            if sub_count == 0:
                nodes.append({
                    'id': sub_bn,
                    'label': break_bizname(safe_str(row['사업자명'])),
                    'title': safe_str(row['사업자명']),
                    'color': {
                        'background': "#fff6f6",
                        'border': 'rgba(0,0,0,0)'
                    },
                    'borderWidth': 0,
                    'shape': 'circle',
                    'font': {'size': 14, 'multi': True},
                    'size': 10,
                    'x': x,
                    'y': y
                })
                edges.append({'from': parent_biznum, 'to': sub_bn})
                node_info[sub_bn] = {
                    '사업자명': row['사업자명'],
                    '사업자등록번호': format_biznum(sub_bn),
                    '대표자명': row['대표자명'],
                    '사업장소재지': row['사업장소재지'],
                    'CSO신고번호': row.get('CSO신고번호', ''),
                    '재위탁업체': sub_count
                }
                user_idx += 1
                continue
            nodes.append({
                'id': sub_bn,
                'label': break_bizname(safe_str(row['사업자명'])),
                'title': safe_str(row['사업자명']),
                'color': '#FFB1B1',
                'shape': 'circle',
                'font': {'size': 14, 'multi': True},
                'size': size if size else 20,
                'x': x,
                'y': y
            })
            edges.append({'from': parent_biznum, 'to': sub_bn})
            node_info[sub_bn] = {
                '사업자명': row['사업자명'],
                '사업자등록번호': format_biznum(sub_bn),
                '대표자명': row['대표자명'],
                '사업장소재지': row['사업장소재지'],
                'CSO신고번호': row.get('CSO신고번호', ''),
                '재위탁업체': sub_count
            }
            user_idx += 1

    return jsonify({
        'nodes': nodes,
        'edges': edges,
        'node_info': node_info
    })

def calc_radius(n, min_radius=50, max_radius=100):
    if n <= 1:
        return max_radius
    return max(min_radius, int(max_radius / (n ** 0.5)))

def preprocess_df(users_df, contracts_df, subcontracts_df):
    users_df['사업자등록번호'] = users_df['사업자등록번호'].astype(str).str.strip()
    users_df['Email'] = users_df['Email'].astype(str).str.strip()
    contracts_df['위탁-사업자등록번호'] = contracts_df['위탁-사업자등록번호'].astype(str).str.strip()
    contracts_df['수탁-사업자등록번호'] = contracts_df['수탁-사업자등록번호'].astype(str).str.strip()
    for col in [5, 6, 7]:
        subcontracts_df[subcontracts_df.columns[col]] = subcontracts_df[subcontracts_df.columns[col]].astype(str).str.strip()
    return users_df, contracts_df, subcontracts_df

def add_node(nodes, bn, info):
    # 노드 추가 코드
    pass

if __name__ == '__main__':
    app.run(debug=True)