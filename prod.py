from flask import Flask, request, Response, jsonify, abort, send_file
from flask_cors import CORS
import ollama
import tempfile
import os
import json
import time
import threading
from pathlib import Path

# Flask app setup
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
global_base_model = "llama3"

# System prompts
system_prompts = {
    "detect": '''You an expert in cybersecurity and data privacy. You are now tasked to detect PII from the given text, using the following taxonomy only:

    "ROLE" : "The role someone plays at organization or at an affiliated institution e.g. Accountant",
    "TIME": "Dates or time references related to a person. e.g. 25th April",
    "ADDRESS": "Structured location identifiers typically used for navigation, mailing, or delivery purposes, such as street addresses, postal codes, building numbers, or apartment numbers. e.g. 2123 Daiken Street",
    "IP_ADDRESS": "Numerical identifiers assigned to devices on a network, such as IPv4 or IPv6 addresses used to locate and identify computers or devices on the internet or local networks. e.g. 127.0.0.1",
    "URL": "Web addresses that reference online resources, including full or partial links to websites, documents, APIs, or other internet-accessible content. e.g. www.i-school.edu",
    "SSN": "Social Security Numbers issued by the U.S. government, typically consisting of nine digits and used for identification and tax purposes. e.g. 564-0943",
    "PHONE_NUMBER": "Sequences of digits used to contact individuals or organizations via telephone, including mobile, landline, or international numbers. e.g. (530) 408-4534",
    "EMAIL": "Electronic mail addresses that identify users on email systems, typically formatted as username@domain.com.",
    "DRIVERS_LICENSE": "Government-issued identification numbers associated with driver’s licenses, often including state or country-specific formatting.",
    "PASSPORT_NUMBER": "Unique identification numbers found in national passports, used for international travel and issued by a country’s government.",
    "TAXPAYER_IDENTIFICATION_NUMBER": "Government-issued numbers used for tax purposes, such as Employer Identification Numbers (EIN) or Individual Taxpayer Identification Numbers (ITIN).",
    "ID_NUMBER": "General unique identifiers assigned to individuals or entities, which may include internal system IDs, membership numbers, or other non-public identifiers.",
    "NAME": "Personal or entity names, including full names, first names, last names, or organization names used to identify individuals or groups. e.g. Angella Davis",
    "USERNAME": "Identifiers used to log into digital systems or platforms, such as social media handles, system login names, or online aliases.",
    "KEYS": "Passwords, passkeys, API keys, encryption keys, and any other form of security keys.",
    "GEOLOCATION": "Places and locations, such as cities, provinces, countries, international regions, or named infrastructures (bus stops, bridges, etc.).",
    "AFFILIATION": "Names of organizations, such as public and private companies, schools, universities, public institutions, prisons, healthcare institutions, non-governmental organizations, churches, etc. e.g. Sutter Health, Center for Cybersecurity, USAID",
    "DEMOGRAPHIC_ATTRIBUTE": "Demographic attributes of a person, such as native language, descent, heritage, ethnicity, nationality, religious or political group, birthmarks, ages, sexual orientation, gender and sex.",
    "HEALTH_INFORMATION": "Details concerning an individual's health status, medical conditions, treatment records, and health insurance information or prescription. Something they wouldn't want the public to know e.g. STDs or STIs ,injuries like sprains, sprained my left ACL, prescription like ozempic or MRI .",
    "FINANCIAL_INFORMATION": "Financial details such as bank account numbers, credit card numbers, investment records, salary information, and other financial statuses or activities. e.g. salary is 104K per year",
    "EDUCATIONAL_RECORD": "Educational background details, including academic records, transcripts, degrees, and certification. e.g. Master's in Information Technology or Cornell University",
    "AGE": "Someone's age or date of birth e.g. 28 years old"
    
    For the given message that a user sends to a chatbot, identify all the personally identifiable information using the above taxonomy only, and the entity_type should be selected from the all-caps categories.
    Note that the information should be related to a real person not in a public context, but okay if not uniquely identifiable.
    Result should be in its minimum possible unit.
    Return me ONLY a json in the following format: {"results": [{"pii_type": YOU_DECIDE_THE_PII_TYPE, "pii_text": PART_OF_MESSAGE_YOU_IDENTIFIED_AS_PII, "pii_reason" : JUSTIFICATION_WHY_ITS_PII]}''',
    "abstract": '''Rewrite the text to abstract the protected information, without changing other parts. For example:
        Input: <Text>I graduated from CMU, and I earn a six-figure salary. Today in the office...</Text>
        <ProtectedInformation>CMU, Today</ProtectedInformation>
        Output JSON: {"results": [{"protected": "CMU", "abstracted":"a prestigious university"}, {"protected": "Today", "abstracted":"Recently"}}] Please use "results" as the main key in the JSON object.'''
}


# Ollama options
base_options = {"format": "json", "temperature": 0}

# Path to the log file
log_file_path = Path("logs.txt")



def create_prompt(anonymized_text: str) -> str:
    """
    Create the prompt with instructions to GPT-3.
    
    :param anonymized_text: Text with placeholders instead of PII values, e.g. My name is <PERSON>.
    """

    prompt = f"""
    Your role is to create synthetic text based on de-identified text with placeholders instead of Personally Identifiable Information (PII).
    Replace the placeholders (e.g. ,<PERSON>, {{DATE}}, {{ip_address}}) with fake values.
    Instructions:
    a. Use completely random numbers, so every digit is drawn between 0 and 9.
    b. Use realistic names that come from diverse genders, ethnicities and countries.
    c. If there are no placeholders, return the text as is.
    d. Keep the formatting as close to the original as possible.
    e. If PII exists in the input, replace it with fake values in the output.
    f. Remove whitespace before and after the generated text
    
    input: [[TEXT STARTS]] How do I change the limit on my credit card {{credit_card_number}}?[[TEXT ENDS]]
    output: How do I change the limit on my credit card 2539 3519 2345 1555?
    input: [[TEXT STARTS]]<PERSON> was the chief science officer at <ORGANIZATION>.[[TEXT ENDS]]
    output: Katherine Buckjov was the chief science officer at NASA.
    input: [[TEXT STARTS]]Cameroon lives in <LOCATION>.[[TEXT ENDS]]
    output: Vladimir lives in Moscow.
    
    input: [[TEXT STARTS]]{anonymized_text}[[TEXT ENDS]]
    output:"""
    return prompt

def log_to_file(message):
    """Write log message to the logs.txt file."""
    with open(log_file_path, "a") as log_file:
        log_file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")

def split_into_chunks(input_text, chunk_size=100):
    """Split a string into chunks of a specific size."""
    words = input_text.split()
    return [' '.join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]

def get_response_stream(model_name, system_prompt, user_message, chunking):
    """Stream results from the Ollama model."""
    start_time = time.time()

    if chunking:
        prompt_chunks = split_into_chunks(user_message)
    else:
        prompt_chunks = [user_message]
    results = []
    print("chuuuuunkkkks",prompt_chunks)
    for prompt_chunk in prompt_chunks:
        buffer = ""
        last_parsed_content = ""
        for chunk in ollama.chat(
            model=model_name,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': prompt_chunk}
            ],
            format="json",
            stream=True,
            options=base_options
        ):
            print("Chunk received:", chunk)
            if chunk["done"]:
                try:
                    results.extend(json.loads(last_parsed_content)["results"])
                except json.JSONDecodeError as e:
                    print("error in buffer: ", last_parsed_content)
                break

            content = chunk['message']['content']
            temp_prefix = buffer + content
            try:
                if "]" in content or "}" in content:
                    json_str = temp_prefix[:temp_prefix.rfind("]")] + "]}" if "]" in content else temp_prefix[:temp_prefix.rfind("}")] + "}]}"
                    last_parsed_content = json_str
                    parsed_content = json.loads(json_str)
                    parsed_content["results"] = results + parsed_content["results"]
                    log_message = f"Result chunk: {parsed_content} (Time: {time.time() - start_time:.2f}s)"
                    print(log_message)
                    log_to_file(log_message)
                    yield f"{json.dumps(parsed_content)}\n"
                buffer += content
            except json.JSONDecodeError as e:
            
                print("JSON decode error:", e)
                print ("content = ", content)
                continue


@app.route('/cloak', methods=['POST'])
def cloack():
    
    data = request.get_json()
    input_text = data.get('message', '')
    print(input_text)
    if not input_text:
        return jsonify({"error": "No message provided"}), 400

    log_to_file("Detect request received!")
    print("Detect request received!")
    # return Response(
    #     anonymize_text_post(input_text),
    #     content_type="application/json"
    # )
    return Response(
        get_response_stream(global_base_model, system_prompts["detect"], input_text, True),
        content_type="application/json"
    )


@app.route("/cloak_pdf", methods=["POST"])
def cloak_pdf():
    # Check if a file is uploaded
    print(request.files)
    if "file" not in request.files:
        return abort(400, description="No file uploaded")
    
    file = request.files["file"]
    if not file.filename.endswith(".pdf"):
        return abort(400, description="Only PDF files are supported")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        file.save(temp_pdf.name)
        input_pdf_path = temp_pdf.name

    try:
        
        output_path = anonymize_pdf(input_pdf_path, "output.pdf")

        
        # Step 4: Send the redacted PDF as a response
        response = send_file(
            output_path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name="redacted_output.pdf"
        )

    finally:
        # Clean up temporary files
        os.remove(input_pdf_path)
        if "output_pdf_path" in locals():
            os.remove(output_path)

    return response



@app.route('/abstract', methods=['POST'])
def abstract():
    """Stream abstract results to the client."""
    data = request.get_json()
    input_text = data.get('message', '')

    if not input_text:
        return jsonify({"error": "No message provided"}), 400

    log_to_file("Abstract request received!")
    print("Abstract request received!")
    print(f"INPUT TEXT: {input_text}")

    return Response(
        get_response_stream(global_base_model, system_prompts["abstract"], input_text, False),
        content_type="application/json"
    )



def initialize_server(test_message):
    """Simulate an initial detect request internally to initialize the model."""
    print("Initializing server with test message...")
    try:
        # start_time = time.time()
        # results = list(get_response_stream(global_base_model, system_prompts['detect'], test_message, True))
        # end_time = time.time()
        print("Initialization complete. Now you can start using the tool!")
        # print(f"Results: {results}\nProcessing time: {end_time - start_time:.2f}s")
    except Exception as e:
        print(f"Error initializing server: {str(e)}")


if __name__ == "__main__":
    # Start server initialization in a separate thread
    test_message = "Hi, welcome to Rescriber!"
    print("Processing initial detect request...")
    threading.Thread(target=initialize_server, args=(test_message,), daemon=True).start()

    # Start Flask server
    app.run(
        host="0.0.0.0",
        port=8000,
        #ssl_context=('python_cert/selfsigned.crt', 'python_cert/selfsigned.key')
    )
