import streamlit as st
import openai
import requests
import json
import time
from datetime import date, timedelta
from urllib.parse import quote_plus

# ------------------------------------------------------------------------------
# 1) STREAMLIT CONFIG: Must be the first command
# ------------------------------------------------------------------------------
st.set_page_config(page_title="Maui Itinerary Planner (RAG)", layout="centered")

# ------------------------------------------------------------------------------
# 2) OPENAI & SERPAPI SETUP
# ------------------------------------------------------------------------------
client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
SERPAPI_KEY = st.secrets.get("SERPAPI_API_KEY", None)
SERPAPI_BASE_URL = "https://serpapi.com/search.json"

# ------------------------------------------------------------------------------
# 3) HELPER FUNCTIONS
# ------------------------------------------------------------------------------

def get_questions():
    """
    Generate 3 user-friendly questions about the trip from GPT-4o.
    """
    system_prompt = "You are a friendly travel assistant helping plan a trip."
    user_prompt = (
        "Provide three short, thoughtful questions about a traveler's preferences. "
        "Return them as a JSON list of exactly three strings, no extra text."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o",  # Using 'gpt-4o' as requested
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
    1) Asks GPT for custom search queries based on user answers, dates, and location.
    2) For each query, calls SerpAPI and caches the results.
    """
    system_prompt = (
        "You are an advanced travel planner. "
        "The user has certain preferences, travel dates, and a location. "
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

    # Ask GPT for the search queries
    try:
        ai_response = client.chat.completions.create(
            model="gpt-4o",
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
        queries = [
            f"Dining in {location}",
            f"Must-see events in {location}",
            f"Fun outdoor activities in {location}"
        ]

    # For each query, call SerpAPI
    results = {}
    if SERPAPI_KEY:
        for q in queries:
            results[q] = fetch_serpapi_data(q, location)
    else:
        for q in queries:
            results[q] = {}

    return {
        "search_queries": queries,
        "search_results": results
    }

def fetch_serpapi_data(query, location, retries=3):
    """
    Query SerpAPI for the top Google results, focusing on 'organic_results' and any 
    'local_results' or 'places' data. We'll attempt to parse out rating, address, phone, etc.
    """
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
            resp = requests.get(SERPAPI_BASE_URL, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        time.sleep(2)
    return {}

def gather_rag_data(all_search_data):
    """
    Gather relevant data from SerpAPI results, including rating, phone, snippet, address, etc.
    We'll pass this to GPT as bullet points for 'RAG' usage.
    """
    queries = all_search_data.get("search_queries", [])
    results_dict = all_search_data.get("search_results", {})

    if not queries:
        return "(No extra data found.)"

    lines = []
    for q in queries:
        data = results_dict.get(q, {})
        # 1) Possibly get 'organic_results'
        if "organic_results" in data:
            org_items = data["organic_results"][:2]  # up to 2
            for item in org_items:
                title = item.get("title", "Untitled")
                link = item.get("link", "")
                snippet = item.get("snippet", "")
                line = f"- Title: {title}\n  Link: {link}\n  Snippet: {snippet[:120]}..."
                lines.append(line)

        # 2) Possibly get 'local_results' or 'local_map' data
        if "local_results" in data:
            local_items = data["local_results"].get("places", [])[:2]  # up to 2
            for item in local_items:
                title = item.get("title", "Untitled")
                rating = item.get("rating", "No rating")
                reviews = item.get("reviews", "No reviews info")
                address = item.get("address", "")
                phone = item.get("phone", "")
                line = (
                    f"- Local: {title}\n  "
                    f"Rating: {rating}, Reviews: {reviews}\n  "
                    f"Address: {address}\n  "
                    f"Phone: {phone}"
                )
                lines.append(line)

    if not lines:
        return "(No extra data found.)"
    return "\n".join(lines)


def generate_itinerary(user_answers, trip_start, trip_end, location, all_search_data):
    """
    Build a short day-by-day itinerary that references the SERP data for RAG usage. 
    We'll pass details from gather_rag_data(...) into the GPT prompt so it can incorporate them.
    """
    # Gather a short list of relevant details from SerpAPI
    rag_snippet = gather_rag_data(all_search_data)

    system_prompt = (
        "You create a concise, day-by-day travel plan in Markdown, referencing real data from the user. "
        "Incorporate places, addresses, or phone numbers if relevant. Offer short reasons for each mention. "
        "Keep it minimal and well-formatted. Avoid disclaimers or code references."
    )

    user_input = f"""Location: {location}
Trip Dates: {trip_start} to {trip_end}
Preferences:
1) {user_answers[0]}
2) {user_answers[1]}
3) {user_answers[2]}

Here is extra data from search results (RAG), which may include rating, phone, snippet, etc.:

{rag_snippet}

Please weave some of this info into a short day-by-day plan (friendly Markdown).
"""

    try:
        ai_response = client.chat.completions.create(
            model="gpt-4o",
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
# 4) STREAMLIT APP
# ------------------------------------------------------------------------------
# 4a) Session state
if "dynamic_questions" not in st.session_state:
    st.session_state.dynamic_questions = get_questions()

if "cached_search_data" not in st.session_state:
    st.session_state.cached_search_data = {}

if "itinerary_text" not in st.session_state:
    st.session_state.itinerary_text = None

# 4b) UI
st.markdown("# Plan Your Maui Adventure (RAG Edition)")
st.markdown("Get a short day-by-day itinerary that references real data from the web, seamlessly embedded!")

# Let user choose any location
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

            # Fetch or reuse the search data
            if user_ans_tuple not in st.session_state.cached_search_data:
                st.info("Gathering extra data for your trip (RAG style)...")
                new_data = hidden_search_for_more_ideas(
                    (user_answer1.strip(), user_answer2.strip(), user_answer3.strip()),
                    start_date_val,
                    end_date_val,
                    location_val.strip()
                )
                st.session_state.cached_search_data[user_ans_tuple] = new_data

            st.info("Creating your itinerary with real data references...")
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
                st.success("Your itinerary is ready! Scroll down to see it.")


# ------------------------------------------------------------------------------
# 5) DISPLAY ITINERARY
# ------------------------------------------------------------------------------
if st.session_state.itinerary_text:
    st.markdown("---")
    st.markdown("## Your Day-by-Day Plan")
    st.markdown(st.session_state.itinerary_text)  # GPT's final output in Markdown

    # Let user share / download
    itinerary_txt = st.session_state.itinerary_text
    st.download_button(
        label="Share This Itinerary",
        data=itinerary_txt,
        file_name="my_maui_rag_itinerary.txt",
        mime="text/plain"
    )
    email_subject = quote_plus("Check out my Maui trip plan!")
    email_body = quote_plus(itinerary_txt)
    mailto_link = f"mailto:?subject={email_subject}&body={email_body}"
    st.markdown(f"[Email This Itinerary]({mailto_link})")

    st.markdown("---")
    st.markdown("## More Ideas from the Web")
    user_ans_tuple = (
        st.session_state.ans1.strip(),
        st.session_state.ans2.strip(),
        st.session_state.ans3.strip(),
        str(start_date_val),
        str(end_date_val),
        location_val.strip(),
    )
    if user_ans_tuple not in st.session_state.cached_search_data:
        st.write("No extra data found. Please plan your trip first.")
    else:
        # Show the raw queries & top results, in case the user wants to see them
        search_info = st.session_state.cached_search_data[user_ans_tuple]
        queries = search_info.get("search_queries", [])
        results_dict = search_info.get("search_results", {})

        if not queries:
            st.write("We didn't find more ideas at this time.")
        else:
            for q in queries:
                st.markdown(f"### {q}")
                data = results_dict.get(q, {})
                # Show top 2 or 3 results from organic_results
                if "organic_results" in data:
                    top_items = data["organic_results"][:3]
                    for item in top_items:
                        title = item.get("title", "Untitled")
                        link = item.get("link", "#")
                        snippet = item.get("snippet", "")
                        st.markdown(f"**{title}**")
                        st.write(snippet)
                        st.markdown(f"[Learn more]({link})")

                # If there's local results
                if "local_results" in data:
                    places = data["local_results"].get("places", [])[:3]
                    for place in places:
                        title = place.get("title", "Untitled")
                        rating = place.get("rating", "No rating")
                        reviews = place.get("reviews", "No reviews info")
                        address = place.get("address", "No address")
                        phone = place.get("phone", "No phone")
                        st.markdown(f"**{title}**")
                        st.write(f"Rating: {rating}, Reviews: {reviews}")
                        st.write(f"Address: {address}")
                        st.write(f"Phone: {phone}")
                st.markdown("---")
