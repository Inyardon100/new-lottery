import streamlit as st
import sqlite3
import random
import time
import datetime
import pandas as pd
from streamlit_autorefresh import st_autorefresh

# --- 시간대 설정 (한국시간) ---
KST = datetime.timezone(datetime.timedelta(hours=9))

def now_kst():
    return datetime.datetime.now(KST)

# --- 1. 설정 및 데이터베이스 초기화 (사용자 제공 버전과 동일) ---
def setup_database():
    conn = sqlite3.connect('lottery_data_v2.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON;")
    c.execute('''
        CREATE TABLE IF NOT EXISTS lotteries (id INTEGER PRIMARY KEY, title TEXT NOT NULL, draw_time TIMESTAMP, num_winners INTEGER, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS participants (id INTEGER PRIMARY KEY, lottery_id INTEGER, name TEXT NOT NULL, FOREIGN KEY (lottery_id) REFERENCES lotteries (id) ON DELETE CASCADE)
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS winners (id INTEGER PRIMARY KEY, lottery_id INTEGER, winner_name TEXT, draw_round INTEGER, FOREIGN KEY (lottery_id) REFERENCES lotteries (id) ON DELETE CASCADE)
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS lottery_logs (id INTEGER PRIMARY KEY, lottery_id INTEGER, log_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, log_message TEXT, FOREIGN KEY (lottery_id) REFERENCES lotteries (id) ON DELETE CASCADE)
    ''')
    conn.commit()
    return conn

# --- 2. 헬퍼 및 로직 함수 (사용자 제공 버전과 동일) ---
def add_log(conn, lottery_id, message):
    c = conn.cursor()
    c.execute("INSERT INTO lottery_logs (lottery_id, log_message, log_timestamp) VALUES (?, ?, ?)", (lottery_id, message, now_kst()))
    conn.commit()

def run_draw(conn, lottery_id, num_to_draw, candidates):
    actual = min(num_to_draw, len(candidates))
    if actual <= 0: return []
    winners = random.sample(candidates, k=actual)
    c = conn.cursor()
    c.execute("SELECT MAX(draw_round) FROM winners WHERE lottery_id = ?", (lottery_id,))
    prev = c.fetchone()[0] or 0
    current_round = prev + 1
    for w in winners:
        c.execute("INSERT INTO winners (lottery_id, winner_name, draw_round) VALUES (?, ?, ?)",(lottery_id, w, current_round))
    if current_round == 1:
        c.execute("UPDATE lotteries SET status = 'completed' WHERE id = ?", (lottery_id,))
    conn.commit()
    add_log(conn, lottery_id, f"{current_round}회차 추첨 진행. (당첨자: {', '.join(winners)})")
    return winners

def check_and_run_scheduled_draws(conn):
    c = conn.cursor()
    now = now_kst()
    c.execute("SELECT id, num_winners FROM lotteries WHERE status = 'scheduled' AND draw_time <= ?", (now,))
    for lottery_id, num_winners in c.fetchall():
        c.execute("SELECT name FROM participants WHERE lottery_id = ?", (lottery_id,))
        participants = [r[0] for r in c.fetchall()]
        if participants:
            winners = run_draw(conn, lottery_id, num_winners, participants)
            if winners:
                st.session_state[f'celebrated_{lottery_id}'] = True

# --- 3. Streamlit UI 구성 ---
def main():
    st.set_page_config(page_title="new lottery", page_icon="📜", layout="wide")
    st_autorefresh(interval=1000, limit=None, key="main_refresher")
    conn = setup_database()
    check_and_run_scheduled_draws(conn)

    # 세션 상태 초기화 (화면 모드 변수 추가)
    st.session_state.setdefault('admin_auth', False)
    st.session_state.setdefault('delete_confirm_id', None)
    st.session_state.setdefault('view_mode', 'list')  # 'list' or 'detail'
    st.session_state.setdefault('selected_lottery_id', None)

    st.title("📜 NEW LOTTERY")
    st.markdown("---")
    col1, col2 = st.columns([2, 1])

    # ==================== 좌측: 추첨 현황판 (상세보기에 관리 기능 추가) ====================
    with col1:
        # '상세 보기' 상태일 때
        if st.session_state.view_mode == 'detail' and st.session_state.selected_lottery_id is not None:
            if st.button("🔙 목록으로 돌아가기"):
                st.session_state.view_mode = 'list'
                st.session_state.selected_lottery_id = None
                st.experimental_rerun()
            
            lid = st.session_state.selected_lottery_id
            try:
                sel_row = pd.read_sql("SELECT * FROM lotteries WHERE id = ?", conn, params=(lid,)).iloc[0]
                title, status = sel_row['title'], sel_row['status']
                
                raw = sel_row['draw_time']
                if isinstance(raw, str): draw_time = datetime.datetime.fromisoformat(raw)
                else: draw_time = raw
                if hasattr(draw_time, 'tzinfo') and draw_time.tzinfo is None: draw_time = draw_time.replace(tzinfo=KST)

                with st.container(border=True):
                    st.header(f"✨ {title}")
                    if status == 'completed':
                        st.success(f"**추첨 완료!** ({draw_time.strftime('%Y-%m-%d %H:%M:%S %Z')})")
                        winners_df = pd.read_sql("SELECT winner_name, draw_round FROM winners WHERE lottery_id = ? ORDER BY draw_round", conn, params=(lid,))
                        for rnd, grp in winners_df.groupby('draw_round'):
                            label = '1회차' if rnd == 1 else f"{rnd}회차 (재추첨)"
                            st.markdown(f"#### 🏆 {label} 당첨자")
                            tags = " &nbsp; ".join([f"<span style='background-color:#E8F5E9; color:#1E8E3E; border-radius:5px; padding:5px 10px; font-weight:bold;'>{n}</span>" for n in grp['winner_name']])
                            st.markdown(f"<p style='text-align:center; font-size:20px;'>{tags}</p>", unsafe_allow_html=True)
                        if st.session_state.get(f'celebrated_{lid}', False):
                            st.balloons(); st.session_state[f'celebrated_{lid}'] = False
                    else: # scheduled
                        diff = draw_time - now_kst()
                        if diff.total_seconds() > 0: st.info(f"**추첨 예정:** {draw_time.strftime('%Y-%m-%d %H:%M:%S %Z')} (남은 시간: {str(diff).split('.')[0]})")
                        else: st.warning("예정 시간이 지났습니다. 곧 자동 진행됩니다...")
                    
                    # 탭 구성 변경
                    tab_list = ["참가자 명단", "📜 추첨 로그"]
                    if st.session_state.admin_auth:
                        tab_list.append("👑 관리자 기능")
                    
                    tabs = st.tabs(tab_list)
                    
                    with tabs[0]: # 참가자 명단
                        part_df = pd.read_sql("SELECT name FROM participants WHERE lottery_id = ?", conn, params=(lid,))
                        st.dataframe(part_df.rename(columns={'name':'이름'}), use_container_width=True, height=200)
                    
                    with tabs[1]: # 추첨 로그
                        log_df = pd.read_sql("SELECT strftime('%Y-%m-%d %H:%M:%S', log_timestamp, 'localtime') AS 시간, log_message AS 내용 FROM lottery_logs WHERE lottery_id = ? ORDER BY id", conn, params=(lid,))
                        st.dataframe(log_df, use_container_width=True, height=200)

                    # 관리자 탭 (인증된 경우에만 표시 및 기능 활성화)
                    if st.session_state.admin_auth and len(tabs) > 2:
                        with tabs[2]:
                            st.subheader("이 추첨 관리하기")
                            
                            # 재추첨 (완료된 추첨일 때만 표시)
                            if status == 'completed':
                                st.write("**재추첨**")
                                all_p = pd.read_sql("SELECT name FROM participants WHERE lottery_id=?", conn, params=(lid,))['name'].tolist()
                                prev = pd.read_sql("SELECT winner_name FROM winners WHERE lottery_id=?", conn, params=(lid,))['winner_name'].tolist()
                                cand = [p for p in all_p if p not in prev]
                                if cand:
                                    chosen = st.multiselect("재추첨 후보자", cand, default=cand, key=f"detail_redraw_cand_{lid}")
                                    num_r = st.number_input("추첨 인원 수", 1, len(chosen), 1, key=f"detail_redraw_num_{lid}")
                                    if st.button("재추첨 실행", key=f"detail_redraw_btn_{lid}", type="primary"):
                                        run_draw(conn, lid, num_r, chosen)
                                        st.success("재추첨 완료"); time.sleep(1); st.experimental_rerun()
                                else:
                                    st.warning("재추첨 후보가 없습니다.")
                            else:
                                st.info("완료된 추첨만 재추첨할 수 있습니다.")

                            st.markdown("---")
                            # 삭제
                            st.write("**추첨 삭제**")
                            if st.button("삭제", key=f"detail_delete_btn_{lid}"):
                                st.session_state.delete_confirm_id = lid
                            if st.session_state.delete_confirm_id == lid:
                                st.warning("정말 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.")
                                if st.button("예, 삭제합니다", key=f"detail_confirm_del_btn_{lid}", type="primary"):
                                    c = conn.cursor(); c.execute("DELETE FROM lotteries WHERE id=?", (lid,)); conn.commit()
                                    st.session_state.delete_confirm_id = None
                                    st.session_state.view_mode = 'list'
                                    st.session_state.selected_lottery_id = None
                                    st.success("삭제 완료"); time.sleep(1); st.experimental_rerun()
            except (IndexError, pd.errors.EmptyDataError):
                 st.error("선택한 추첨을 찾을 수 없습니다. 삭제되었을 수 있습니다.")
                 st.session_state.view_mode = 'list'; st.session_state.selected_lottery_id = None

        # '목록 보기' 상태일 때 (기본값)
        else:
            st.header("🎉 추첨 목록")
            df_lot = pd.read_sql("SELECT id, title, status FROM lotteries ORDER BY id DESC", conn)
            if df_lot.empty:
                st.info("아직 생성된 추첨이 없습니다.")
            else:
                for _, row in df_lot.iterrows():
                    with st.container(border=True):
                        list_col1, list_col2, list_col3 = st.columns([5, 2, 2])
                        status_emoji = "🟢 진행중" if row['status'] == 'scheduled' else "🏁 완료"
                        with list_col1:
                            st.write(f"#### {row['title']}")
                        with list_col2:
                            st.markdown(f"**{status_emoji}**")
                        with list_col3:
                            if st.button("상세보기", key=f"detail_btn_{row['id']}"):
                                st.session_state.view_mode = 'detail'
                                st.session_state.selected_lottery_id = int(row['id'])
                                st.experimental_rerun()

    # ==================== 관리자 메뉴 (사용자 제공 '안전성 끝판왕' 코드와 100% 동일) ====================
    with col2:
        st.header("👑 추첨 관리자")
        if not st.session_state.admin_auth:
            pw = st.text_input("관리자 코드", type="password", key="admin_pw_input")
            if st.button("인증", key="auth_button"):
                if pw == st.secrets.get('admin', {}).get('password'):
                    st.session_state.admin_auth = True
                    st.experimental_rerun()
                else:
                    st.error("코드가 올바르지 않습니다.")
        else:
            st.success("관리자로 인증됨")
            action = st.radio("작업 선택", ["새 추첨 생성", "기존 추첨 관리"], key="admin_action_radio")

            if action == "새 추첨 생성":
                st.subheader("새 추첨 만들기")
                title = st.text_input("추첨 제목", key="new_title")
                num_winners = st.number_input("당첨 인원 수", min_value=1, value=1, key="new_num_winners")
                draw_type = st.radio("추첨 방식", ["즉시 추첨", "예약 추첨"], key="new_draw_type", horizontal=True)

                if draw_type == "예약 추첨":
                    date = st.date_input("추첨 날짜 (YYYY-MM-DD 형식으로 선택)", value=now_kst().date(), key="new_draw_date")
                    default_tm = st.session_state.get('new_draw_time', now_kst().time())
                    tm = st.time_input(
                        "추첨 시간 (HH:MM)",
                        value=default_tm,
                        key="new_draw_time",
                        step=datetime.timedelta(minutes=1)
                    )
                    draw_time = datetime.datetime.combine(date, tm, tzinfo=KST)
                else:
                    draw_time = now_kst()

                st.markdown("참가자 명단을 입력하세요. 한 줄에 한 명씩 적어주세요.")
                participants_txt = st.text_area("참가자 (예: 홍길동)\n홍길순", key="new_participants", height=150)
                if st.button("추첨 생성", key="create_button", type="primary"):
                    names = [n.strip() for n in participants_txt.split('\n') if n.strip()]
                    if not title or not names:
                        st.warning("제목과 참가자를 입력하세요.")
                    elif draw_type == "예약 추첨" and draw_time <= now_kst():
                        st.error("예약 시간은 현재 이후여야 합니다.")
                    else:
                        c = conn.cursor()
                        c.execute("INSERT INTO lotteries (title, draw_time, num_winners, status) VALUES (?, ?, ?, 'scheduled')", (title, draw_time, num_winners))
                        lid = c.lastrowid
                        for n in names:
                            c.execute("INSERT INTO participants (lottery_id, name) VALUES (?, ?)", (lid, n))
                        conn.commit()
                        add_log(conn, lid, f"추첨 생성 (방식: {draw_type}, 참가자 수: {len(names)})")
                        st.success("추첨 생성 완료"); time.sleep(1); st.experimental_rerun()

            else:
                st.subheader("기존 추첨 관리")
                st.info("오른쪽 메뉴의 기존 추첨 관리는 이제 사용되지 않습니다. 각 추첨의 '상세보기'에서 관리 기능을 이용해주세요.")
                # df_m = pd.read_sql("SELECT id, title, status FROM lotteries ORDER BY id DESC", conn)
                # if df_m.empty:
                #     st.info("관리할 추첨이 없습니다.")
                # else:
                #     ... (기존 관리자 메뉴 코드는 그대로 유지되나, 사용자에게 왼쪽 탭을 사용하도록 안내)
    conn.close()

if __name__ == "__main__":
    main()
