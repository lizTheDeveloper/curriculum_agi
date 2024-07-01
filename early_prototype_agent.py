## a tiny POC agent with function calling

import json
import os
import importlib.util
from openai import OpenAI

client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

# Dictionary to store function objects
function_objects = {}

def prompt_model(messages, temperature=0.7, max_tokens=2048, model="lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF/Meta-Llama-3-8B-Instruct-Q4_K_M.gguf", max_retries=20):
    print("Prompting model...")
    print(messages)
    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json"},
                max_tokens=max_tokens
            )
            result = completion.choices[0].message.content
            messages.append({"role": "user", "content": completion.choices[0].message.content})
            if result == "":
                print("Empty response. Retrying...")
                messages.append({"role": "user", "content": "Your previous response was empty. Please retry."})
                continue
            return json.loads(result)
        except json.JSONDecodeError as e:
            print(completion.choices[0].message.content)
            print(messages)
            print(f"Attempt {attempt + 1}: Failed to parse JSON. Retrying...")
            messages.append({"role": "user", "content": "Your previous response was invalid. Please retry. Please respond only with JSON so we can retry the result. Here's the error we got: " + str(e)})
            ## loop through the messages array and remove any messages that have an empty content field
        except Exception as e:
            print(f"Attempt {attempt + 1}: An error occurred: {str(e)}. Retrying...")
        
        messages = [message for message in messages if message.get('content', None) is not None]
    
    raise RuntimeError(f"Failed to get valid response from model after {max_retries} attempts")

def extract_function_info(code, function_name):
    prompt = f"""
    Analyze the following Python function and extract its parameters and required fields.
    Respond with a JSON object containing two keys: "parameters" and "required".
    "parameters" should be an object where each key is a parameter name and the value describes the parameter.
    "required" should be an array of parameter names that are required.

    Function:
    ```python
    {code}
    ```
    Respond with one message, or one tool call, in JSON format only. You will be re-prompted to continue after your message or tool call is processed.
    Please respond with only JSON, you MUST respond with JSON. Do not respond with any other text, do not explain yourself, do not explain the code, only provide the code, with no markdown, no fenced code block, in JSON format.
    """
    
    result = prompt_model([{"role": "system", "content": prompt}], temperature=0.3, max_tokens=1024)
    return result

def generate_and_run_tests(code, function_name):
    prompt = f"""
    You are a test engineer. Write a test suite for the following Python function:
    ```python
    {code}
    ```
    Provide the test suite as a string that can be executed. Include various test cases to ensure the function works correctly.
    """
    
    test_suite = prompt_model([{"role": "system", "content": prompt}], temperature=0.3, max_tokens=2048)
    
    # Save the function to a temporary file
    with open(f"{function_name}.py", "w") as f:
        f.write(str(code))
    
    # Save the test suite to a temporary file
    with open(f"test_{function_name}.py", "w") as f:
        f.write(f"import {function_name}\n")
        f.write(test_suite)
    
    # Run the test suite
    test_result = os.popen(f"python test_{function_name}.py").read()
    
    # Clean up temporary files
    os.remove(f"{function_name}.py")
    os.remove(f"test_{function_name}.py")
    
    return test_suite, test_result

def develop_tool(function_name, initial_requirements):
    messages = [
        {"role": "system", "content": "You are a skilled Python developer. Your task is to create a function based on the given requirements and improve it based on test results."},
        {"role": "user", "content": f"Create a Python function named {function_name} that meets these requirements: {initial_requirements}"}
    ]
    
    max_iterations = 5
    for i in range(max_iterations):
        code = prompt_model(messages)
        print("*********** DEVELOP TOOL ***********")
        print(code)
        print("*********** DEVELOP TOOL ***********")
        
        test_suite, test_result = generate_and_run_tests(code, function_name)
        
        if "FAILED" not in test_result:
            print(f"Function {function_name} developed successfully after {i+1} iterations.")
            return code, test_suite, test_result
        
        messages.append({"role": "assistant", "content": json.dumps({"code": code})})
        messages.append({"role": "user", "content": f"The function failed some tests. Here are the test results:\n{test_result}\nPlease improve the function to pass all tests."})
    
    print(f"Failed to develop function {function_name} after {max_iterations} iterations.")
    return None, None, None

def create_tool(function_name, requirements):
    code, test_suite, test_result = develop_tool(function_name, requirements)
    
    if code is None:
        return f"Failed to create function '{function_name}' that meets the requirements and passes all tests."
    
    # Extract function info
    function_info = extract_function_info(code, function_name)
    
    # Save the code to a file
    filename = f"{function_name}.py"
    with open(filename, "w") as f:
        f.write(code)
    
    # Import the function
    spec = importlib.util.spec_from_file_location(function_name, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    # Store the function object
    function_objects[function_name] = getattr(module, function_name)
    
    # Add the function definition to our list
    function_def = {
        "name": function_name,
        "description": f"Dynamically created function: {function_name}",
        "parameters": function_info["parameters"],
        "required": function_info["required"]
    }
    functions.append(function_def)
    
    return f"Function '{function_name}' has been created, tested, and added to available tools.\nTest suite:\n{test_suite}\nTest results:\n{test_result}"

# List to store function definitions
functions = [
    {
        "name": "create_tool",
        "description": "Creates a new tool (Python function) that can be used later",
        "parameters": {
            "type": "object",
            "properties": {
                "function_name": {"type": "string", "description": "The name of the new function"},
                "requirements": {"type": "string", "description": "The requirements for the new function"}
            },
            "required": ["function_name", "requirements"]
        }
    }
]

def get_system_message():
    base_message = """
Your role is to respond with either a single message or a single tool call in JSON format only with no other text. Messages should be formatted as JSON, and any other explanatory text should be formatted as JSON. Do not respond outside of the JSON format, do not produce fenced code blocks, only JSON.
For messages, use the following structure:
{
    "type": "message",
    "content": "Your message here",
    "finished": false
}

For tool calls, use the OpenAI function-calling standard:
{
    "type": "function",
    "function": {
        "name": "function_name",
        "arguments": {
            "arg1": "value1",
            "arg2": "value2"
        }
    }
}

You can also create new tools using the create_tool function:
{
    "type": "function",
    "function": {
        "name": "create_tool",
        "arguments": {
            "function_name": "name_of_new_function",
            "requirements": "Description of what the function should do"
        }
    }
}

When you're finished with the task, send a final message with "finished": true.

Available functions:
"""
    return base_message + json.dumps(functions, indent=2)

def run_agent_step(messages):
    return prompt_model(messages)

def process_tool_call(tool_call):
    function_name = tool_call['function']['name']
    arguments = tool_call['function']['arguments']
    
    if function_name == 'create_tool':
        return create_tool(arguments['function_name'], arguments['requirements'])
    elif function_name in function_objects:
        try:
            result = function_objects[function_name](**arguments)
            return f"Executed {function_name}. Result: {result}"
        except Exception as e:
            return f"Error executing {function_name}: {str(e)}"
    else:
        return f"Function {function_name} not found, please create the function first."

def run_agent(user_input):
    messages = [
        {"role": "system", "content": get_system_message()},
        {"role": "user", "content": user_input}
    ]
    
    while True:
        response = run_agent_step(messages)
        
        if response['type'] == 'message':
            print("Agent:", response['content'])
            messages.append({"role": "assistant", "content": json.dumps(response)})
            
            if response.get('finished', False):
                break
        elif response['type'] == 'function':
            result = process_tool_call(response)
            print("Function result:", result)
            messages.append({"role": "assistant", "content": json.dumps(response)})
            messages.append({"role": "user", "content": result})
        
        # Uncomment the following line if you want to see the full message history
        print("Current messages:", json.dumps(messages, indent=2))
    
    return messages

# Example usage
user_input = "Create a tool that writes a given string to a given filepath to disk."
final_messages = run_agent(user_input)
print("\nFinal message history:")
print(json.dumps(final_messages, indent=2))
