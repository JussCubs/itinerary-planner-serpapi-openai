import streamlit as st
import openai
import requests
import json
import time
from datetime import date, timedelta
from urllib.parse import quote_plus

# ------------------------------------------------------------------------------
# 1) SETUP: Must be the first Streamlit command
# ------------------------------------------------------------------------------
st.set_page_config(page_title="Maui Itinerary Planner", layout="centered")

# ------------------------------------------------------------------------------
# 2) OPENAI & SERPAPI CONFIG
# ------------------------------------------------------------------------------
client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
SERPAPI_KEY = st.secrets.get("SERPAPI_API_KEY", None)
SERPAPI_BASE_URL = "https://serpapi.com/search.json"


# ------------------------------------------------------------------------------
# 3) HELPER FUNCTIONS
# ------------------------------------------------------------------------------

def get_questions():
    """
    Generate 3 user-friendly questions about the trip.
    """
    system_prompt = "You are a friendly travel assistant helping plan a trip."
    user_prompt = (
        "Provide three short, thoughtful questions about a traveler's preferences. "
        "Return them as a JSON list of exactly three strings, no extra text."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=300
        )
        content = response.choices[0].message.content.strip()
        q_list = json.loads(content)
        if not isinstance(q_list, list) or len(q_list) != 3:
            raise ValueError("Expected exactly 3 questions in a JSON list.")
        return q_list
    except:
        return [
            "What excites you most about traveling there?",
            "What sort of dining do you enjoy?",
            "Do you have any must-do activities (like hiking or snorkeling)?"
        ]


def hidden_search_for_more_ideas(user_answers, trip_start, trip_end, location):
    """
    1) AI suggests custom search queries for the user’s preferences/dates/location.
    2) We call SerpAPI for each query to gather real-world links.
    """
    system_prompt = (
        "You are an advanced travel planner. "
        "The user has certain preferences, trip dates, and a location. "
        "Produce a short JSON: { \"search_queries\": [ ... ] } with relevant queries, no disclaimers or extra text."
    )
    user_context = (
        f"Location: {location}\n"
        f"Trip Dates: {trip_start} to {trip_end}\n"
        f"Preferences:\n"
        f"1) {user_answers[0]}\n"
        f"2) {user_answers[1]}\n"
        f"3) {user_answers[2]}\n"
        "Return only {\"search_queries\": [\"...\"]}."
    )

    try:
        ai_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_context},
            ],
            temperature=0.7,
            max_tokens=600
        )
        raw = ai_response.choices[0].message.content.strip()
        data = json.loads(raw)
        queries = data.get("search_queries", [])
    except:
        # Simple fallback if AI fails
        queries = [
            f"Dining in {location}",
            f"Must-see events in {location}",
            f"Fun outdoor activities in {location}"
        ]

    # Call SerpAPI for each query and store top results
    results = {}
    if SERPAPI_KEY:
        for q in queries:
            results[q] = fetch_serpapi_data(q, location)
    else:
        # If no SerpAPI key, store empty dict
        for q in queries:
            results[q] = {}

    return {
        "search_queries": queries,
        "search_results": results
    }


def fetch_serpapi_data(query, location, retries=3):
    """Call SerpAPI behind the scenes, using user-specified location."""
    if not SERPAPI_KEY:
        return {}
    params = {
        "engine": "google",
        "q": query,
        "location": location,
        "api_key": SERPAPI_KEY,
        "hl": "en",
        "gl": "us"
    }
    for attempt in range(retries):
        try:
            resp = requests.get(SERPAPI_BASE_URL, params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        time.sleep(1)
    return {}


def gather_links_text(all_search_data):
    """
    Gathers up to 2 links from each query's results. 
    Returns a bullet-point text snippet for the AI to reference.
    """
    queries = all_search_data.get("search_queries", [])
    results_dict = all_search_data.get("search_results", {})

    if not queries:
        return "(No extra links found.)"

    lines = []
    for q in queries:
        data = results_dict.get(q, {})
        if "organic_results" not in data:
            continue
        top_items = data["organic_results"][:2]  # up to 2 links
        for item in top_items:
            title = item.get("title", "Untitled")
            link = item.get("link", "#")
            snippet = item.get("snippet", "")
            # We'll keep it short
            lines.append(f"- {title}: {link}\n  ({snippet[:100]}...)")

    if not lines:
        return "(No extra links found.)"
    return "\n".join(lines)


def generate_itinerary(user_answers, trip_start, trip_end, location, all_search_data):
    """
    Build a short day-by-day itinerary that references the SerpAPI links. 
    Explanation: We pass the links to the AI, telling it to mention them 
    concisely in the final plan, with brief 'why' comments.
    """
    # Step 1: Gather a short snippet of links from all_search_data
    links_snippet = gather_links_text(all_search_data)

    # Step 2: System + user prompt
    system_prompt = (
        "You create a concise, day-by-day travel plan. "
        "Use a friendly tone. Include short references to the provided links, explaining in a few words "
        "why each spot is interesting. Keep it short and minimal. No disclaimers or code references."
    )

    user_input = (
        f"Location: {location}\n"
        f"Trip Dates: {trip_start} to {trip_end}\n"
        f"Preferences:\n"
        f"1) {user_answers[0]}\n"
        f"2) {user_answers[1]}\n"
        f"3) {user_answers[2]}\n\n"
        "Below are some useful links found online:\n"
        f"{links_snippet}\n\n"
        "Please incorporate a few of them into the day-by-day plan with short reasons. "
        "Keep it minimal, no disclaimers, no filler."
    )

    try:
        ai_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            temperature=0.8,
            max_tokens=1600
        )
        return ai_response.choices[0].message.content.strip()
    except:
        return None


# ------------------------------------------------------------------------------
# 4) STREAMLIT APP STATE + UI
# ------------------------------------------------------------------------------
# 4a) Initialize session state
if "dynamic_questions" not in st.session_state:
    st.session_state.dynamic_questions = get_questions()

# { (answer1, answer2, answer3, start_date, end_date, location): {search_queries, search_results} }
if "cached_search_data" not in st.session_state:
    st.session_state.cached_search_data = {}

if "itinerary_text" not in st.session_state:
    st.session_state.itinerary_text = None

# 4b) UI
st.markdown("# Plan Your Next Adventure")
st.markdown("Create a concise itinerary with helpful links for further research!")

location_val = st.text_input("Where are you going?", value="Maui, Hawaii")

col1, col2 = st.columns(2)
with col1:
    start_date_val = st.date_input("When does your trip begin?", value=date.today())
with col2:
    end_date_val = st.date_input("When does your trip end?", value=date.today() + timedelta(days=5))

st.subheader("Your Preferences")
with st.form("trip_form"):
    user_answer1 = st.text_input(st.session_state.dynamic_questions[0], key="ans1")
    user_answer2 = st.text_input(st.session_state.dynamic_questions[1], key="ans2")
    user_answer3 = st.text_input(st.session_state.dynamic_questions[2], key="ans3")

    plan_btn = st.form_submit_button("Plan My Adventure")

    if plan_btn:
        if start_date_val > end_date_val:
            st.error("Please ensure your start date is before your end date.")
        else:
            user_ans_tuple = (
                user_answer1.strip(),
                user_answer2.strip(),
                user_answer3.strip(),
                str(start_date_val),
                str(end_date_val),
                location_val.strip(),
            )
            # If we don't have search data for this combo yet, fetch it
            if user_ans_tuple not in st.session_state.cached_search_data:
                st.info("Gathering extra ideas for your trip...")
                new_data = hidden_search_for_more_ideas(
                    (user_answer1.strip(), user_answer2.strip(), user_answer3.strip()),
                    start_date_val,
                    end_date_val,
                    location_val.strip()
                )
                st.session_state.cached_search_data[user_ans_tuple] = new_data

            # Always generate a fresh itinerary
            st.info("Putting together your itinerary with helpful links...")
            search_data_for_ai = st.session_state.cached_search_data[user_ans_tuple]
            new_itinerary = generate_itinerary(
                (user_answer1.strip(), user_answer2.strip(), user_answer3.strip()),
                start_date_val,
                end_date_val,
                location_val.strip(),
                search_data_for_ai
            )
            if new_itinerary is None:
                st.error("Something went wrong. Please try again.")
            else:
                st.session_state.itinerary_text = new_itinerary
                st.success("Your itinerary is ready! Scroll down to check it out.")


# ------------------------------------------------------------------------------
# 5) DISPLAY ITINERARY
# ------------------------------------------------------------------------------
if st.session_state.itinerary_text:
    st.markdown("---")
    st.markdown("## Your Day-by-Day Plan")
    st.markdown(st.session_state.itinerary_text)

    # Share / Download
    itinerary_txt = st.session_state.itinerary_text
    st.download_button(
        label="Share This Itinerary",
        data=itinerary_txt,
        file_name="my_trip_itinerary.txt",
        mime="text/plain"
    )
    email_subject = quote_plus("Check out my trip plan!")
    email_body = quote_plus(itinerary_txt)
    mailto_link = f"mailto:?subject={email_subject}&body={email_body}"
    st.markdown(f"[Email This Itinerary]({mailto_link})")

    # Extra Ideas (show the queries + top results)
    st.markdown("---")
    st.markdown("## More Ideas to Explore")
    user_ans_tuple = (
        st.session_state.ans1.strip(),
        st.session_state.ans2.strip(),
        st.session_state.ans3.strip(),
        str(start_date_val),
        str(end_date_val),
        location_val.strip(),
    )
    if user_ans_tuple not in st.session_state.cached_search_data:
        st.write("No extra ideas found yet. Please plan your trip first.")
    else:
        search_info = st.session_state.cached_search_data[user_ans_tuple]
        queries = search_info.get("search_queries", [])
        results_dict = search_info.get("search_results", {})

        if not queries:
            st.write("We couldn't find more ideas at this time.")
        else:
            for q in queries:
                st.markdown(f"### {q}")
                data = results_dict.get(q, {})
                if "organic_results" not in data:
                    st.write("*(No extra suggestions found.)*")
                    st.markdown("---")
                    continue
                # Show top 2 or 3 results
                top_items = data["organic_results"][:3]
                for item in top_items:
                    title = item.get("title", "Untitled")
                    link = item.get("link", "#")
                    snippet = item.get("snippet", "")
                    st.markdown(f"**{title}**")
                    st.write(snippet)
                    st.markdown(f"[Learn more]({link})")
                st.markdown("---")
