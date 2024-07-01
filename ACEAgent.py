## current implementation by claude, some unimplemented parts

import json
import os
import importlib.util
from openai import OpenAI

client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

class ACEAgent:
    def __init__(self, model_configs):
        self.model_configs = model_configs
        self.function_objects = {}
        self.functions = [
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

    def prompt_model(self, messages, model_config, max_retries=20):
        for attempt in range(max_retries):
            try:
                completion = client.chat.completions.create(
                    model=model_config["model"],
                    messages=messages,
                    temperature=model_config["temperature"],
                    response_format={"type": "json"},
                    max_tokens=model_config["max_tokens"]
                )
                result = completion.choices[0].message.content
                messages.append({"role": "user", "content": completion.choices[0].message.content})
                if result == "":
                    messages.append({"role": "user", "content": "Your previous response was empty. Please retry."})
                    continue
                return json.loads(result)
            except json.JSONDecodeError as e:
                messages.append({"role": "user", "content": "Your previous response was invalid. Please retry. Please respond only with JSON so we can retry the result. Here's the error we got: " + str(e)})
            except Exception as e:
                print(f"Attempt {attempt + 1}: An error occurred: {str(e)}. Retrying...")
            
            messages = [message for message in messages if message.get('content', None) is not None]
        
        raise RuntimeError(f"Failed to get valid response from model after {max_retries} attempts")

    def extract_function_info(self, code, function_name):
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
        
        result = self.prompt_model([{"role": "system", "content": prompt}], self.model_configs["function_info"], max_retries=1)
        return result

    def generate_and_run_tests(self, code, function_name):
        prompt = f"""
        You are a test engineer. Write a test suite for the following Python function:
        ```python
        {code}  
        ```
        Provide the test suite as a string that can be executed. Include various test cases to ensure the function works correctly.
        """
        
        test_suite = self.prompt_model([{"role": "system", "content": prompt}], self.model_configs["test_generation"], max_retries=1)
        
        # Save and run tests, then clean up (same as before)
        ...

        return test_suite, test_result

    def develop_tool(self, function_name, initial_requirements):
        messages = [
            {"role": "system", "content": "You are a skilled Python developer. Your task is to create a function based on the given requirements and improve it based on test results."},
            {"role": "user", "content": f"Create a Python function named {function_name} that meets these requirements: {initial_requirements}"}
        ]
        
        max_iterations = 5
        for i in range(max_iterations):
            code = self.prompt_model(messages, self.model_configs["tool_development"], max_retries=1)

            test_suite, test_result = self.generate_and_run_tests(code, function_name)
            
            if "FAILED" not in test_result:
                print(f"Function {function_name} developed successfully after {i+1} iterations.")
                return code, test_suite, test_result
            
            messages.append({"role": "assistant", "content": json.dumps({"code": code})})
            messages.append({"role": "user", "content": f"The function failed some tests. Here are the test results:\n{test_result}\nPlease improve the function to pass all tests."})
        
        print(f"Failed to develop function {function_name} after {max_iterations} iterations.")
        return None, None, None

    def create_tool(self, function_name, requirements):
        code, test_suite, test_result = self.develop_tool(function_name, requirements)
        
        if code is None:
            return f"Failed to create function '{function_name}' that meets the requirements and passes all tests."
        
        # Extract function info, save code, import function (same as before)
        ...
        
        # Store the function object 
        self.function_objects[function_name] = getattr(module, function_name)
        
        # Add the function definition to our list
        function_def = {
            "name": function_name, 
            "description": f"Dynamically created function: {function_name}",
            "parameters": function_info["parameters"],
            "required": function_info["required"]
        }
        self.functions.append(function_def)
        
        return f"Function '{function_name}' has been created, tested, and added to available tools.\nTest suite:\n{test_suite}\nTest results:\n{test_result}"

    def get_system_message(self):
        # Same as before, but uses self.functions
        ...

    def run_agent_step(self, messages):
        selected_config = self.model_configs["agent_step"]
        return self.prompt_model(messages, selected_config)

    def process_tool_call(self, tool_call):
        function_name = tool_call['function']['name']
        arguments = tool_call['function']['arguments']
        
        if function_name == 'create_tool':
            return self.create_tool(arguments['function_name'], arguments['requirements'])
        elif function_name in self.function_objects:
            try:
                result = self.function_objects[function_name](**arguments)
                return f"Executed {function_name}. Result: {result}"
            except Exception as e:
                return f"Error executing {function_name}: {str(e)}"
        else:
            return f"Function {function_name} not found, please create the function first."

    def run_agent(self, user_input):
        messages = [
            {"role": "system", "content": self.get_system_message()},
            {"role": "user", "content": user_input}
        ]
        
        while True:
            response = self.run_agent_step(messages)
            
            if response['type'] == 'message':
                print("Agent:", response['content'])
                messages.append({"role": "assistant", "content": json.dumps(response)})
                
                if response.get('finished', False):
                    break
            elif response['type'] == 'function':
                result = self.process_tool_call(response)
                print("Function result:", result)
                messages.append({"role": "assistant", "content": json.dumps(response)})
                messages.append({"role": "user", "content": result})
        
        return messages
