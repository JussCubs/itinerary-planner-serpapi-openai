import streamlit as st
import openai
import requests
import json
import time
from datetime import date, timedelta

# ------------------------------------------------------------------------------
# Set up OpenAI client
# ------------------------------------------------------------------------------
client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
SERPAPI_API_KEY = st.secrets["SERPAPI_API_KEY"]

# ------------------------------------------------------------------------------
# Helper function to generate three dynamic questions at once
# ------------------------------------------------------------------------------
def get_questions():
    prompt = (
        "You are a helpful itinerary planning assistant for a trip to Maui. "
        "Generate three engaging and dynamic questions for a traveler planning a Maui vacation. "
        "Each question should build upon the potential answer of the previous question. "
        "Return the three questions as a JSON array. Example format:\n"
        '["First question?", "Second question?", "Third question?"]'
    )
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful itinerary planning assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=150,
        )
        content = response.choices[0].message.content.strip()
        questions = json.loads(content)
        if not isinstance(questions, list) or len(questions) != 3:
            raise ValueError("Expected a list of three questions")
        return questions
    except Exception as e:
        st.error(f"Error generating questions: {e}")
        return [
            "What is one thing you are most excited to experience in Maui?",
            "What type of cuisine are you most interested in exploring while in Maui?",
            "Do you have any special interests or activities (e.g., hiking, snorkeling, culture) that you'd like to prioritize?"
        ]

# ------------------------------------------------------------------------------
# Function to generate a full itinerary using OpenAI based on the conversation and dates
# ------------------------------------------------------------------------------
def generate_itinerary(conversation_history, start_date, end_date):
    system_prompt = (
        "You are an expert travel itinerary planner for Maui. Based on the traveler's preferences "
        "and travel dates, generate a detailed itinerary. Include events, restaurants, scenic spots, "
        "tours, and adventure activities. Also, provide 'serpapi_queries' for each category (events, restaurants, "
        "scenery, tours, adventures) for additional details via SerpAPI. Return as valid JSON with keys: "
        "'itinerary' and 'serpapi_queries'."
    )

    conversation_text = "\n".join([f"Q: {q['question']}\nA: {q['answer']}" for q in conversation_history])

    user_prompt = (
        f"Travel Dates: {start_date} to {end_date}\n"
        f"Preferences:\n{conversation_text}\n\n"
        "Generate the itinerary in JSON format."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=1000,
        )
        content = response.choices[0].message.content.strip()
        itinerary_data = json.loads(content)
        return itinerary_data
    except json.JSONDecodeError:
        st.error("Failed to parse itinerary JSON. Here is the raw response:")
        st.text(content)
        return None
    except Exception as e:
        st.error(f"Error generating itinerary: {e}")
        return None

# ------------------------------------------------------------------------------
# Function to call SerpAPI with error handling and retries
# ------------------------------------------------------------------------------
def call_serpapi(query, retries=3):
    base_url = "https://serpapi.com/search.json"
    params = {
        "engine": "google",
        "q": query,
        "location": "Maui, Hawaii",
        "api_key": SERPAPI_API_KEY,
    }
    attempt = 0
    while attempt < retries:
        try:
            response = requests.get(base_url, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                st.warning(f"SerpAPI returned status code {response.status_code}. Retrying...")
        except Exception as e:
            st.warning(f"Error calling SerpAPI: {e}. Retrying...")
        attempt += 1
        time.sleep(2)
    st.error("Failed to fetch data from SerpAPI after multiple attempts.")
    return {}

# ------------------------------------------------------------------------------
# Initialize session state variables
# ------------------------------------------------------------------------------
if "questions" not in st.session_state:
    st.session_state.questions = get_questions()

if "itinerary_generated" not in st.session_state:
    st.session_state.itinerary_generated = False

# ------------------------------------------------------------------------------
# App UI: Title, description, and travel date selection
# ------------------------------------------------------------------------------
st.title("Maui Itinerary Planner")
st.markdown("Plan an exciting trip to Maui with dynamic itinerary suggestions based on your preferences.")

# Date selection
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Select Start Date", value=date.today())
with col2:
    end_date = st.date_input("Select End Date", value=date.today() + timedelta(days=7))
if start_date > end_date:
    st.error("Start date must be before end date.")

# ------------------------------------------------------------------------------
# Form: Ask all three questions at once
# ------------------------------------------------------------------------------
st.header("Tell us about your Maui trip!")
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
            st.session_state.itinerary_generated = True
            st.session_state.itinerary_data = itinerary_data
            st.success("Itinerary generated successfully!")
        else:
            st.error("Failed to generate itinerary. Please try again.")

# ------------------------------------------------------------------------------
# Display the itinerary and SerpAPI details
# ------------------------------------------------------------------------------
if st.session_state.itinerary_generated:
    st.subheader("Your Dynamic Maui Itinerary")
    st.json(st.session_state.itinerary_data.get("itinerary", {}))
    
    serpapi_queries = st.session_state.itinerary_data.get("serpapi_queries", {})
    if serpapi_queries:
        st.subheader("Additional Details via SerpAPI")
        for category, query in serpapi_queries.items():
            st.markdown(f"**{category.capitalize()} Search**")
            st.write(f"Query: {query}")
            result = call_serpapi(query)
            st.json(result)
    else:
        st.info("No SerpAPI queries provided in the itinerary data.")
