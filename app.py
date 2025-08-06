import streamlit as st
import sqlite3
import random
import time
import datetime
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- 1. 설정 및 데이터베이스 초기화 ---
def setup_database():
    """데이터베이스 연결 및 테이블 생성 함수"""
    conn = sqlite3.connect('lottery_data_v2.db', check_same_thread=False)
    c = conn.cursor()
    # Cascade 삭제 옵션을 위해 외래 키 제약 조건을 활성화합니다.
    c.execute("PRAGMA foreign_keys = ON;")
    
    # 추첨 정보를 저장하는 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS lotteries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            draw_time TIMESTAMP NOT NULL,
            num_winners INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 참가자 정보를 저장하는 테이블
    # lottery_id가 삭제되면 관련된 참가자도 자동으로 삭제됩니다 (ON DELETE CASCADE)
    c.execute('''
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lottery_id INTEGER,
            name TEXT NOT NULL,
            FOREIGN KEY (lottery_id) REFERENCES lotteries (id) ON DELETE CASCADE
        )
    ''')
    # 당첨자 정보를 저장하는 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lottery_id INTEGER,
            winner_name TEXT NOT NULL,
            draw_round INTEGER NOT NULL,
            FOREIGN KEY (lottery_id) REFERENCES lotteries (id) ON DELETE CASCADE
        )
    ''')
    # 추첨 활동 로그를 저장하는 테이블
    c.execute('''
        CREATE TABLE IF NOT EXISTS lottery_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lottery_id INTEGER,
            log_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            log_message TEXT NOT NULL,
            FOREIGN KEY (lottery_id) REFERENCES lotteries (id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    return conn

# --- 2. 헬퍼 및 로직 함수 ---
def add_log(conn, lottery_id, message):
    """추첨 로그를 DB에 추가하는 함수"""
    c = conn.cursor()
    c.execute("INSERT INTO lottery_logs (lottery_id, log_message) VALUES (?, ?)", (lottery_id, message))
    conn.commit()

def run_draw(conn, lottery_id, num_to_draw, candidates):
    """실제 추첨을 실행하고 결과를 DB에 저장하는 함수"""
    actual_num_winners = min(num_to_draw, len(candidates))
    if actual_num_winners <= 0:
        return []
    
    winners = random.sample(candidates, k=actual_num_winners)
    
    c = conn.cursor()
    c.execute("SELECT MAX(draw_round) FROM winners WHERE lottery_id = ?", (lottery_id,))
    max_round = c.fetchone()[0]
    current_round = (max_round or 0) + 1

    for winner in winners:
        c.execute("INSERT INTO winners (lottery_id, winner_name, draw_round) VALUES (?, ?, ?)",
                  (lottery_id, winner, current_round))
    
    c.execute("UPDATE lotteries SET status = 'completed' WHERE id = ?", (lottery_id,))
    conn.commit()
    
    log_message = f"{current_round}회차 추첨 진행. (당첨자: {', '.join(winners)})"
    add_log(conn, lottery_id, log_message)
    return winners

def check_and_run_scheduled_draws(conn):
    """예약된 추첨을 자동으로 실행하는 함수"""
    c = conn.cursor()
    now = datetime.datetime.now()
    c.execute("SELECT id, num_winners FROM lotteries WHERE status = 'scheduled' AND draw_time <= ?", (now,))
    scheduled_lotteries = c.fetchall()

    for lottery_id, num_winners in scheduled_lotteries:
        c.execute("SELECT name FROM participants WHERE lottery_id = ?", (lottery_id,))
        participants = [row[0] for row in c.fetchall()]
        if participants:
            winners = run_draw(conn, lottery_id, num_winners, participants)
            if winners:
                st.session_state[f'celebrated_{lottery_id}'] = True

# --- 3. Streamlit UI 구성 (최종 안정화 버전) ---
def main():
    st.set_page_config(page_title="new lottery", page_icon="📜", layout="wide")
    st_autorefresh(interval=5000, limit=None, key="main_refresher")
    conn = setup_database()
    check_and_run_scheduled_draws(conn)

    # 페이지가 로드될 때마다 세션 상태 변수가 있는지 확인하고 없으면 초기화
    if 'admin_auth' not in st.session_state:
        st.session_state['admin_auth'] = False
    if 'delete_confirm_id' not in st.session_state:
        st.session_state['delete_confirm_id'] = None

    st.title("📜 NEW LOTTERY")
    st.markdown("---")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.header("🎉 추첨 현황판")
        st.markdown("이 페이지는 최신 상태를 반영합니다.")
        
        try:
            lotteries_df = pd.read_sql("SELECT id, title, draw_time, status, num_winners FROM lotteries ORDER BY id DESC", conn)
        except Exception:
            lotteries_df = pd.DataFrame()

        if lotteries_df.empty:
            st.info("아직 생성된 추첨이 없습니다. 관리자가 추첨을 만들어주세요.")
        else:
            for index, row in lotteries_df.iterrows():
                lottery_id = int(row['id'])
                title = row['title']
                status = row['status']
                draw_time = pd.to_datetime(row['draw_time'])

                with st.container(border=True):
                    st.subheader(f"✨ {title}")
                    
                    winners_df = pd.read_sql("SELECT winner_name, draw_round FROM winners WHERE lottery_id = ? ORDER BY draw_round", conn, params=(lottery_id,))
                    if not winners_df.empty:
                        st.success(f"**추첨 완료!** ({draw_time.strftime('%Y-%m-%d %H:%M:%S')})")
                        for round_num, group in winners_df.groupby('draw_round'):
                            round_text = f"{round_num}회차" if round_num == 1 else f"{round_num}회차 (재추첨)"
                            st.markdown(f"#### 🏆 {round_text} 당첨자")
                            winner_tags = " &nbsp; ".join([f"<span style='background-color:#E8F5E9; color:#1E8E3E; border-radius:5px; padding:5px 10px; font-weight:bold;'>{name}</span>" for name in group['winner_name']])
                            st.markdown(f"<p style='text-align:center; font-size: 20px;'>{winner_tags}</p>", unsafe_allow_html=True)

                        if st.session_state.get(f'celebrated_{lottery_id}', False):
                            st.balloons()
                            st.session_state[f'celebrated_{lottery_id}'] = False
                    
                    else:
                        time_diff = draw_time - datetime.datetime.now()
                        if time_diff.total_seconds() > 0:
                            st.info(f"**추첨 예정:** {draw_time.strftime('%Y-%m-%d %H:%M:%S')} (남은 시간: {str(time_diff).split('.')[0]})")
                        else:
                            st.warning("예정 시간이 지났습니다. 곧 추첨이 자동으로 진행됩니다...")
                    
                    tab1, tab2 = st.tabs(["참가자 명단", "📜 추첨 로그"])
                    with tab1:
                        participants_df = pd.read_sql("SELECT name FROM participants WHERE lottery_id = ?", conn, params=(lottery_id,))
                        st.dataframe(participants_df.rename(columns={'name': '이름'}), use_container_width=True, height=150)
                    with tab2:
                        logs_df = pd.read_sql("SELECT strftime('%Y-%m-%d %H:%M:%S', log_timestamp, 'localtime') as '시간', log_message as '내용' FROM lottery_logs WHERE lottery_id = ? ORDER BY id", conn, params=(lottery_id,))
                        st.dataframe(logs_df, use_container_width=True, height=150)

    with col2:
        st.header("👑 추첨 관리자 메뉴")

        # 최종 해결책: CSS로 로그인 폼과 관리자 패널의 가시성을 제어
        if st.session_state.admin_auth:
            login_style = "display: none;"
            admin_panel_style = "display: block;"
        else:
            login_style = "display: block;"
            admin_panel_style = "display: none;"

        st.markdown(f"""
            <style>
            .login-container {{ {login_style} }}
            .admin-panel-container {{ {admin_panel_style} }}
            </style>
        """, unsafe_allow_html=True)

        # 로그인 폼 컨테이너 (항상 렌더링되지만 CSS로 숨겨질 수 있음)
        with st.container():
            st.markdown('<div class="login-container">', unsafe_allow_html=True)
            password = st.text_input("관리자 코드를 입력하세요.", type="password", key="admin_pw_input")
            if st.button("인증", key="auth_button"):
                try:
                    if password == st.secrets["admin"]["password"]:
                        st.session_state.admin_auth = True
                        st.rerun() # 인증 성공 시 즉시 새로고침하여 CSS 스타일을 변경
                    else:
                        st.error("코드가 올바르지 않습니다.")
                except KeyError:
                    st.error("Secrets 설정을 확인해주세요. 관리자 코드가 설정되지 않았습니다.")
                except Exception as e:
                    st.error(f"예상치 못한 오류가 발생했습니다: {e}")
            st.markdown('</div>', unsafe_allow_html=True)

        # 관리자 패널 컨테이너 (항상 렌더링되지만 CSS로 숨겨질 수 있음)
        with st.container():
            st.markdown('<div class="admin-panel-container">', unsafe_allow_html=True)
            st.success("관리자로 인증되었습니다.")
            
            admin_action = st.radio("작업 선택", ["새 추첨 만들기", "기존 추첨 관리 (재추첨/삭제)"], key="admin_action_radio")

            if admin_action == "새 추첨 만들기":
                st.subheader("새 추첨 만들기")
                title = st.text_input("추첨 제목", key="new_title")
                num_winners = st.number_input("당첨 인원 수", 1, value=1, key="new_num_winners")
                draw_type = st.radio("추첨 방식", ["즉시 추첨", "예약 추첨"], horizontal=True, key="new_draw_type")
                
                draw_time = st.datetime_input("추첨 시간", value=datetime.datetime.now() + datetime.timedelta(minutes=5),
                                              key="new_draw_time", disabled=(draw_type == "즉시 추첨"))
                
                participants_text = st.text_area("참가자 명단 (한 줄에 한 명, 중복 가능)", key="new_participants")
                
                if st.button("✅ 추첨 생성", type="primary", key="create_button"):
                    participants = [name.strip() for name in participants_text.split('\n') if name.strip()]
                    if not title or not participants:
                        st.warning("제목과 참가자를 입력하세요.")
                    elif draw_type == "예약 추첨" and draw_time <= datetime.datetime.now():
                        st.error("예약 시간은 현재 시간 이후여야 합니다.")
                    else:
                        final_draw_time = draw_time if draw_type == "예약 추첨" else datetime.datetime.now()
                        c = conn.cursor()
                        c.execute("INSERT INTO lotteries (title, draw_time, num_winners, status) VALUES (?, ?, ?, 'scheduled')",
                                  (title, final_draw_time, num_winners))
                        lottery_id = c.lastrowid
                        for p_name in participants:
                            c.execute("INSERT INTO participants (lottery_id, name) VALUES (?, ?)", (lottery_id, p_name))
                        conn.commit()
                        add_log(conn, lottery_id, f"추첨 생성됨 (방식: {draw_type}, 총 참가자: {len(participants)}명)")
                        st.success("추첨이 생성되었습니다!"); time.sleep(1); st.rerun()

            elif admin_action == "기존 추첨 관리 (재추첨/삭제)":
                st.subheader("기존 추첨 관리")
                if 'lotteries_df' in locals() and not lotteries_df.empty:
                    choice = st.selectbox("관리할 추첨 선택", options=lotteries_df['title'], key="manage_choice")
                    selected_lottery = lotteries_df[lotteries_df['title'] == choice].iloc[0]
                    lottery_id = int(selected_lottery['id'])

                    if selected_lottery['status'] == 'completed':
                        st.write(f"**'{choice}' 재추첨**")
                        all_participants = pd.read_sql("SELECT name FROM participants WHERE lottery_id = ?", conn, params=(lottery_id,))['name'].tolist()
                        prev_winners = pd.read_sql("SELECT winner_name FROM winners WHERE lottery_id = ?", conn, params=(lottery_id,))['winner_name'].tolist()
                        candidates = [p for p in all_participants if p not in prev_winners]
                        if not candidates:
                            st.warning("재추첨할 수 있는 후보가 없습니다.")
                        else:
                            final_candidates = st.multiselect("재추첨 후보자", options=list(set(candidates)), default=list(set(candidates)), key="redraw_candidates")
                            num_redraw_winners = st.number_input("추가 당첨 인원", min_value=1, max_value=len(final_candidates) if final_candidates else 1, value=1, key="redraw_num_winners")
                            if st.button("🚀 재추첨 실행", type="primary", key="redraw_button"):
                                if final_candidates:
                                    run_draw(conn, lottery_id, num_redraw_winners, final_candidates)
                                    st.success("재추첨이 완료되었습니다!"); time.sleep(1); st.rerun()
                                else:
                                    st.error("재추첨 후보가 없습니다.")
                    else:
                        st.info("완료된 추첨만 재추첨할 수 있습니다.")

                    st.markdown("---")
                    st.write(f"**'{choice}' 영구 삭제**")
                    if st.button("🗑️ 추첨 삭제하기", key=f"delete_btn_{lottery_id}"):
                        st.session_state.delete_confirm_id = lottery_id
                    
                    if st.session_state.delete_confirm_id == lottery_id:
                        st.warning(f"**경고**: '{choice}' 추첨의 모든 기록(참가자, 로그, 당첨자)이 영구적으로 삭제됩니다. 정말로 삭제하시겠습니까?")
                        if st.button("예, 삭제합니다", type="primary", key=f"confirm_delete_btn_{lottery_id}"):
                            c = conn.cursor()
                            c.execute("DELETE FROM lotteries WHERE id = ?", (lottery_id,))
                            conn.commit()
                            st.session_state.delete_confirm_id = None
                            st.success(f"'{choice}' 추첨이 완전히 삭제되었습니다."); time.sleep(2); st.rerun()
                else:
                    st.info("관리할 추첨이 없습니다.")
            st.markdown('</div>', unsafe_allow_html=True)
            
    conn.close()

if __name__ == "__main__":
    main()
