import streamlit as st
import snowflake.connector
from google import genai
from dotenv import load_dotenv
import os
import pandas as pd
import plotly.express as px

try:
    load_dotenv("details.env")
except:
    pass

# ── Snowflake connection ──
def get_snowflake_connection():
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA")
    )

# ── Gemini client ──
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ── Database schema ──
DB_SCHEMA = """
You are an expert SQL assistant for a Snowflake database of an IoT dashboard 
for a steel manufacturing plant (Tata Steel). 

The database is MACHINEBOT, schema RAW. It has these tables:

1. MACHINE_TYPE (mtid, type, created_at, updated_at)
   - 3 rows: GMAW, CLAD, GASCUTTING

2. MACHINES (mid, name, hardware_id, des, msid, mtid, hid, orgid, mcsid, mcid, 
   rpm_multiplication_factor, notify, deleted, created_at, updated_at)
   - 17 physical machines on the factory floor

3. USER (uid, name, email, phno, roleid, hid, orgid, certificate_id, 
   identification_no, password, opid, operator_rfid, deleted, created_at, 
   updated_at, username, current_session_token, active_status, csrf_token, 
   token_created_at, csrf_token2, token_created_at2)
   - 24 employees

4. DEVIATION (hardware_id, oid, shid, start_tm, end_tm, span, type, parameter)
   - 48,484 deviation alerts
   - type: 'high' or 'low'
   - parameter: 'current', 'voltage', 'gas'

5. MACHINE_DERIVED (business_date, shift_name, machine_type, machine_name, oid,
   period_start, period_end, active, idle, inrepair, avg_weld_cur, 
   avg_weld_cur_deviation, avg_weld_volt, avg_weld_volt_deviation, breakdown, 
   target_arc_time, deposit)
   - Shift-level summaries per machine

6. PERIODIC_DATA (business_date, shift_name, machine_type, machine_name, 
   job_name, high_weld_cur_threshold, low_weld_cur_threshold, 
   high_weld_volt_threshold, low_weld_volt_threshold, high_weld_gas_threshold,
   low_weld_gas_threshold, current_deviation_flag, voltage_deviation_flag, 
   gas_deviation_flag, pdid, hardware_id, type, mstatus, weld_cur, weld_volt, 
   weld_gas, hs_temp, amb_temp, rpm, oid, network, tm, travel_in_mm, lpg_flow,
   o2_flow_meter1, o2_flow_meter2, total_lpg_consumption, 
   total_o2_consumption_meter1, total_o2_consumption_meter2, 
   health_status_lpg_flow_meter, health_status_o2_flow_meter1, 
   health_status_o2_flow_meter2, thickness, cut_mm_mtr, created_at, 
   position_start, position_end)
   - 100,000 raw sensor readings
   - mstatus: 'running' or 'stop'
   - type: 'gcm' (gas cutting) or 'pdata' (welding)

7. SUMMARIZE_CLAD_DETAILS_INFO (business_date, shift_name, oid, machine_type,
   machine_name, ontime, offtime, time_span, avg_weld_cur, avg_weld_volt, 
   loss_weight, loss_weight_flag, zero_duration_flag)
   - Per-job cladding sessions

8. SUMMARIZE_GASCUTTING_MACHINE (business_date, shift_name, machine_type, 
   machine_name, on_time, off_time, time_span, net_travel_in_mm, 
   net_lpg_consumption, net_o2_consumption_meter1, net_o2_consumption_meter2, 
   mm_per_min, thickness, cut_mm_mtr, mm_per_min_outlier_flag, no_gas_data_flag)
   - Per-job gas cutting sessions

9. SUMMARIZE_NONGASCUT_MACHINE (business_date, shift_name, machine_type, 
   machine_name, on_time, off_time, time_span, total_lpg_cons, total_heating_o2,
   net_travel_in_mm, mm_per_min, mm_per_min_outlier_flag, stationary_flag)
   - Per-job non-gas cutting sessions

IMPORTANT RULES:
- Always use fully qualified table names: MACHINEBOT.RAW.TABLE_NAME
- Only return the SQL query, nothing else
- No markdown, no backticks, no explanation
- Only SELECT statements — never INSERT, UPDATE, DELETE, DROP
- For machine names use LIKE for partial matches
- Shifts are A, B, C
- The 'active', 'idle', 'inrepair', 'breakdown' columns in MACHINE_DERIVED are in SECONDS
- To convert seconds to hours and minutes use: CONCAT(FLOOR(AVG(active)/3600), 'h ', FLOOR((AVG(active)%3600)/60), 'm')
- Never use TO_VARCHAR with time format on numeric columns
- For time calculations always convert from seconds manually using FLOOR and CONCAT
- If the user says hello, hi, thanks or any greeting — respond with a friendly message, do NOT generate SQL
"""

# ── Convert question to SQL ──
def question_to_sql(question):
    prompt = f"{DB_SCHEMA}\n\nUser: {question}\nRespond with SQL only or a friendly message if it's a greeting:"
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text.strip()

# ── Run SQL on Snowflake ──
def run_query(sql):
    conn = get_snowflake_connection()
    try:
        df = pd.read_sql(sql, conn)
        return df, None
    except Exception as e:
        return None, str(e)
    finally:
        conn.close()

# Adding Grphs to our chatBot
# ── Decide chart type using Gemini ──
def get_chart_type(question, df):
    if len(df) < 2 or len(df.columns) < 2:
        return "none"
    
    prompt = f"""
    The user asked: "{question}"
    The result has columns: {list(df.columns)}
    The result has {len(df)} rows.
    Sample data: {df.head(3).to_string()}
    
    Should this result be displayed as a chart? 
    Reply with ONLY one of these words:
    - bar (for comparisons between categories)
    - line (for trends over time)
    - pie (for distributions/percentages)
    - none (for single values or data that doesn't suit a chart)
    
    Reply with just the single word, nothing else.
    """
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return response.text.strip().lower()
    except:
        return "none"

# ── Plot chart based on type ──
def plot_chart(chart_type, df, question):
    try:
        x_col = df.columns[0]
        y_col = df.columns[1]
        
        if chart_type == "bar":
            fig = px.bar(df, x=x_col, y=y_col, 
                        title=question,
                        color_discrete_sequence=["#E3242B"])
            fig.update_layout(
                plot_bgcolor="#1e1e1e",
                paper_bgcolor="#1e1e1e",
                font_color="white"
            )
            st.plotly_chart(fig, use_container_width=True)

        elif chart_type == "line":
            fig = px.line(df, x=x_col, y=y_col,
                         title=question,
                         color_discrete_sequence=["#E3242B"])
            fig.update_layout(
                plot_bgcolor="#1e1e1e",
                paper_bgcolor="#1e1e1e",
                font_color="white"
            )
            st.plotly_chart(fig, use_container_width=True)

        elif chart_type == "pie":
            fig = px.pie(df, names=x_col, values=y_col,
                        title=question,
                        # 
                        color_discrete_sequence=["#E3242B", "#ff6b6b", "#ff9999"])
            fig.update_layout(
                plot_bgcolor="#1e1e1e",
                paper_bgcolor="#1e1e1e",
                font_color="white"
            )
            st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.warning("Could not plot chart for this result.")

# ── Streamlit UI ──
st.set_page_config(page_title="MachineBOT", page_icon="management_10521901.png", layout="wide")

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700&display=swap');

    body, p, div, span, h1, h2, h3, .stMarkdown {
    font-family: 'Nunito', sans-serif !important;
    }
    [data-testid="stExpander"] * {
        font-family: inherit !important;
    }
    .user-message {
        background-color: #E3242B;
        color: white;
        padding: 12px 16px;
        border-radius: 18px 18px 0px 18px;
        margin: 8px 0;
        max-width: 70%;
        float: right;
        clear: both;
        font-family: 'Nunito', sans-serif !important;
    }
    .bot-message {
        background-color: #2b2b2b;
        color: white;
        padding: 12px 16px;
        border-radius: 18px 18px 18px 0px;
        margin: 8px 0;
        max-width: 70%;
        float: left;
        clear: both;
        font-family: 'Nunito', sans-serif !important;
    }
    .clearfix { clear: both; }
    .streamlit-expanderHeader {
        font-size: 14px !important;
        font-family: 'Nunito', sans-serif !important;
    }
    summary {
        font-size: 14px !important;
    }
    [data-testid="stExpander"] {
        clear: both !important;
        margin-top: 8px !important;
    }
    [data-testid="stExpander"] details summary {
        display: flex !important;
        align-items: center !important;
        gap: 8px !important;
    }
    [data-testid="stExpander"] details summary span {
        font-size: 14px !important;
        font-family: 'Nunito', sans-serif !important;
    }
    [data-testid="stExpander"] details summary svg {
        flex-shrink: 0 !important;
        margin-right: 4px !important;
    }
    [data-testid="stExpander"] summary svg {
    display: none !important;
}
[data-testid="stExpander"] summary::before {
    content: "▶";
    margin-right: 8px;
    font-size: 12px;
}
[data-testid="stExpander"] details[open] summary::before {
    content: "▼";
}
        [data-testid="stExpander"] summary svg,
[data-testid="stExpanderToggleIcon"],
[data-testid="stExpander"] [data-testid*="Icon"] {
    display: none !important;
}
[data-testid="stExpander"] summary > div:first-child {
    display: none !important;
}
[data-testid="stExpander"] summary::before {
    content: "▶";
    margin-right: 8px;
    font-size: 12px;
}
[data-testid="stExpander"] details[open] summary::before {
    content: "▼";
}
    </style>
""", unsafe_allow_html=True)

# st.title("MachineBOT")
col1, col2 = st.columns([1, 15])
with col1:
    st.image("management_10521901.png", width=60)
with col2:
    st.markdown("<h1 style='padding-top: 10px;'>MachineBOT</h1>", unsafe_allow_html=True)
st.caption("<i style='padding-left: 80px;'>Ask questions about your machines!</i>", unsafe_allow_html=True)

# ── Chat history ──
if "messages" not in st.session_state:
    st.session_state.messages = []

# ── Display old messages ──
for msg in st.session_state.messages:
    if msg["role"] == "user":
        st.markdown(f'<div class="user-message">{msg["content"]}</div><div class="clearfix"></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="bot-message">{msg["content"]}</div><div class="clearfix"></div>', unsafe_allow_html=True)
        if "chart_type" in msg and msg["chart_type"] != "none" and "dataframe" in msg:
            plot_chart(msg["chart_type"], msg["dataframe"], msg["content"])
        if "sql" in msg:
            st.markdown('<div class="clearfix"></div>', unsafe_allow_html=True)
            with st.expander("View Query & Table"):
                st.code(msg["sql"], language="sql")
                if "dataframe" in msg:
                    st.dataframe(msg["dataframe"])

# ── Chat input ──
if question := st.chat_input("Ask something... e.g. How many machines are there?"):

    # Show user message

    st.markdown(f'<div class="user-message">{question}</div><div class="clearfix"></div>', unsafe_allow_html=True)
    st.session_state.messages.append({"role": "user", "content": question})

    with st.spinner("Thinking..."):
        sql = question_to_sql(question)

        # Check if Gemini returned SQL or a friendly message
        if sql.strip().upper().startswith("SELECT"):
            df, error = run_query(sql)

            if error:
                error_msg = f"Sorry, I couldn't answer that. Error: {error}"
                st.markdown(f'<div class="bot-message"> {error_msg}</div><div class="clearfix"></div>', unsafe_allow_html=True)
                with st.expander("View Query & Table"):
                    st.code(sql, language="sql")
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": error_msg,
                    "sql": sql
                })
            else:
                explain_prompt = f"""
                The user asked: "{question}"
                The SQL query was: {sql}
                The result was: {df.to_string()}
                Give a short, friendly, plain English answer to the user's question 
                based on the result. Be concise — 1 to 3 sentences max.
                """
                try:
                    explanation = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=explain_prompt
                    )
                    answer = explanation.text
                except Exception as e:
                    answer = "Here are the results — Gemini is busy right now so I can't explain further!"

                import re
                answer_clean = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', answer)
                st.markdown(f'<div class="bot-message"> {answer_clean}</div><div class="clearfix"></div>', unsafe_allow_html=True)
                # st.markdown(f'<div class="bot-message"> {answer}</div><div class="clearfix"></div>', unsafe_allow_html=True)
                
                # Auto plot chart if suitable
                chart_type = get_chart_type(question, df)
                if chart_type != "none":
                    plot_chart(chart_type, df, question)

                st.markdown('<div class="clearfix"></div>', unsafe_allow_html=True)
                with st.expander("View Query & Table"):
                    st.code(sql, language="sql")
                    st.dataframe(df)
                
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer,
                    "dataframe": df,
                    "sql": sql,
                    "chart_type": chart_type
                })
        else:
            # Gemini returned a friendly message instead of SQL
            st.markdown(f'<div class="bot-message"> {sql}</div><div class="clearfix"></div>', unsafe_allow_html=True)
            st.session_state.messages.append({
                "role": "assistant",
                "content": sql
            })

