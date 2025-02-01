import streamlit as st
import openai
import requests
import json
import time
from datetime import date, timedelta

# ------------------------------------------------------------------------------
# 1) SETUP: OpenAI and SerpAPI
# ------------------------------------------------------------------------------
client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
SERPAPI_API_KEY = st.secrets["SERPAPI_API_KEY"]

# We'll define 5 different default SerpAPI search queries
# You can modify them or update them dynamically if you want
DEFAULT_SERPAPI_QUERIES = {
    "events": "Maui events in February 2025",
    "places": "Top attractions in Maui",
    "restaurants": "Best restaurants in Maui",
    "food": "Popular Maui cuisines and local dishes",
    "adventures": "Outdoor adventures in Maui",
}

# ------------------------------------------------------------------------------
# 2) GENERATE QUESTIONS (We do it once, store in session)
# ------------------------------------------------------------------------------
def get_questions():
    """Generate three dynamic questions about Maui preferences using ChatGPT."""
    prompt = (
        "You are a helpful itinerary planning assistant for a trip to Maui. "
        "Generate three engaging questions for a traveler. Each question should "
        "be logically connected, so the second builds on the first, and the third builds on the second. "
        "Return them as a JSON array, e.g.: "
        '["Q1?", "Q2?", "Q3?"].'
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a friendly itinerary planner."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=2000,
        )
        content = response.choices[0].message.content.strip()
        questions = json.loads(content)
        if not isinstance(questions, list) or len(questions) != 3:
            raise ValueError("Expected a list of exactly three questions.")
        return questions
    except Exception as e:
        st.error(f"Error generating questions: {e}")
        # Fallback questions if JSON parse or generation fails
        return [
            "What is one thing you are most excited to experience in Maui?",
            "What type of cuisine are you most interested in exploring while in Maui?",
            "Do you have any special interests or activities (e.g., hiking, snorkeling, culture) that you'd like to prioritize?"
        ]

# ------------------------------------------------------------------------------
# 3) GENERATE ITINERARY
# ------------------------------------------------------------------------------
def generate_itinerary(conversation_history, start_date, end_date):
    """
    Sends user preferences and travel dates to ChatGPT, 
    asking for a day-by-day itinerary in valid JSON.
    We'll also do a retry if JSON parse fails.
    """
    system_prompt = (
        "You are an expert travel itinerary planner for Maui. "
        "The user has told you about their preferences, and you know their travel dates. "
        "Generate a detailed, day-by-day itinerary (for each day from Start Date to End Date) "
        "that includes events, restaurants, scenic spots, tours, and adventure activities. "
        "Finally, produce a JSON object with two keys: 'itinerary' and 'serpapi_queries'. "
        "The 'itinerary' key holds a dictionary of daily plans. The 'serpapi_queries' key "
        "should be a dictionary with multiple categories of search queries relevant to the itinerary, e.g. "
        "events, places, restaurants, food, adventures. The JSON must be valid, complete, and not truncated."
    )

    # Build conversation text from Q&A
    conversation_text = ""
    for turn in conversation_history:
        conversation_text += f"Q: {turn['question']}\nA: {turn['answer']}\n"

    user_content = (
        f"Start Date: {start_date}\n"
        f"End Date: {end_date}\n\n"
        f"Preferences:\n{conversation_text}\n\n"
        "Generate a valid JSON with keys: 'itinerary', 'serpapi_queries'. "
        "Do not include any extra keys, comments, or text outside the JSON."
    )

    # We'll do up to 2 attempts in case the first is incomplete
    max_attempts = 2
    attempt = 0
    while attempt < max_attempts:
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.8,
                max_tokens=2000,  # Increase max tokens to help avoid truncation
            )
            content = response.choices[0].message.content.strip()
            # Attempt to parse as JSON
            itinerary_data = json.loads(content)
            return itinerary_data
        except json.JSONDecodeError:
            # We'll try again, maybe with a more explicit user prompt
            if attempt < max_attempts - 1:
                st.warning("Failed to parse itinerary JSON. Retrying with stricter instructions...")
                user_content += (
                    "\n\nIMPORTANT: The JSON must be valid and fully enclosed in curly braces. "
                    "Double-check you haven't truncated the content."
                )
            else:
                st.error("Failed to parse itinerary JSON after 2 attempts.")
                st.text(content)  # Show raw content
                return None
        except Exception as e:
            st.error(f"Error generating itinerary: {e}")
            return None
        attempt += 1

# ------------------------------------------------------------------------------
# 4) CALL SERPAPI
# ------------------------------------------------------------------------------
def call_serpapi(query, retries=3):
    """
    Calls SerpAPI to get Google search results for the given query, 
    with basic error handling and retries.
    """
    base_url = "https://serpapi.com/search.json"
    params = {
        "engine": "google",
        "q": query,
        "location": "Maui, Hawaii",  # you can tweak location as needed
        "api_key": SERPAPI_API_KEY,
    }
    attempt = 0
    while attempt < retries:
        try:
            response = requests.get(base_url, params=params, timeout=15)
            if response.status_code == 200:
                return response.json()
            else:
                st.warning(f"SerpAPI returned status code {response.status_code}. Retrying...")
        except Exception as e:
            st.warning(f"Error calling SerpAPI: {e}. Retrying...")
        attempt += 1
        time.sleep(2)
    st.error(f"Failed to fetch data from SerpAPI after {retries} attempts.")
    return {}

# ------------------------------------------------------------------------------
# 5) STREAMLIT APP
# ------------------------------------------------------------------------------
# Initialize session state
if "questions" not in st.session_state:
    st.session_state.questions = get_questions()

if "itinerary_generated" not in st.session_state:
    st.session_state.itinerary_generated = False

st.title("Maui Itinerary Planner")
st.markdown("**Plan an exciting trip to Maui** with a dynamic, day-by-day itinerary, plus extra options to swap in.")

# Date selection
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Select Start Date", value=date.today())
with col2:
    end_date = st.date_input("Select End Date", value=date.today() + timedelta(days=7))

# Basic sanity check
if start_date > end_date:
    st.error("Error: Start date must be before end date.")

# Form: Ask the 3 questions in one go
st.header("Tell Us About Your Maui Trip!")
with st.form("questions_form"):
    answer1 = st.text_input(st.session_state.questions[0], key="answer1")
    answer2 = st.text_input(st.session_state.questions[1], key="answer2")
    answer3 = st.text_input(st.session_state.questions[2], key="answer3")
    submitted = st.form_submit_button("Generate Itinerary")
    
    if submitted:
        conversation = [
            {"question": st.session_state.questions[0], "answer": answer1},
            {"question": st.session_state.questions[1], "answer": answer2},
            {"question": st.session_state.questions[2], "answer": answer3},
        ]
        itinerary_data = generate_itinerary(conversation, start_date, end_date)
        if itinerary_data is not None:
            st.session_state.itinerary_data = itinerary_data
            st.session_state.itinerary_generated = True
            st.success("Itinerary generated successfully! Scroll down to see details.")
        else:
            st.error("Failed to generate itinerary. Please try again.")

# ------------------------------------------------------------------------------
# 6) DISPLAY ITINERARY + SERPAPI RESULTS
# ------------------------------------------------------------------------------
if st.session_state.itinerary_generated:
    itinerary_data = st.session_state.itinerary_data
    st.subheader("Your Day-by-Day Maui Itinerary")
    itinerary = itinerary_data.get("itinerary", {})
    st.json(itinerary)

    # We’ll also show the GPT-generated SerpAPI queries from the itinerary
    # plus some default additional queries so the user can see extra ideas
    gpt_serpapi_queries = itinerary_data.get("serpapi_queries", {})
    
    # Merge GPT's queries with our default set, so user sees both
    # If a key is in GPT's queries, it overrides the default
    merged_queries = {**DEFAULT_SERPAPI_QUERIES, **gpt_serpapi_queries}
    
    st.subheader("Additional Ideas & Options (SerpAPI Searches)")
    st.markdown("Below are search results from Google (via SerpAPI) to help you discover **additional** places, events, and activities. You can swap these into your itinerary if you like!")
    
    for category, query in merged_queries.items():
        st.markdown(f"### {category.capitalize()}")
        st.write(f"Search Query: `{query}`")
        results = call_serpapi(query)
        
        # Display raw JSON, or parse out interesting bits
        if "organic_results" in results:
            # Let's show top 3 organic results as suggestions
            top_items = results["organic_results"][:3]
            for idx, item in enumerate(top_items, start=1):
                st.write(f"**Option {idx}:** {item.get('title')}")
                snippet = item.get('snippet', 'No snippet available')
                link = item.get('link', '#')
                st.write(f"*{snippet}*")
                st.write(f"[Learn more here]({link})")
            st.write("---")
        else:
            # If there's no 'organic_results' or parse fails, just show raw JSON
            st.json(results)

    st.info("Feel free to adjust your itinerary by adding/replacing items with these ideas!")
