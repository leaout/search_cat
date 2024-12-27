import time
from ocr import Ocr
from winoperator import WinOperator
from winhandler import WindowHandler
from fuzzywuzzy import process
import json
import os
import requests

def find_best_match(properties, query):
    names =[prop['q'] for prop in properties]
    best_match = process.extractOne(query,names)
    if best_match:
        similarity = best_match[1]
        if similarity < 40:
            return None
        best_name = best_match[0]
        for prop in properties:
            if prop['q'] == best_name:
                return prop
    return None


def parse_json_lines(file_path):

    #返回一个json列表
    json_list = []
    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            try:
                json_data = json.loads(line)
                json_list.append(json_data)
                # yield json_data
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON on line: {line}")
                print(e)
        return json_list
    
def run_select_region(handler, operator, ocr, answer_set):

    x1, y1, x2, y2 = operator.select_screen_region()
    time_delay = 0.5
    while True:
        
        screenshot_data = handler.capture_screenshot_ext(x1, y1, x2, y2)
        #ocr
        question =''.join(ocr.do_ocr_ext(screenshot_data,simple=True))
        if len(question)==0: 
            time.sleep(time_delay)
            continue
        answer = find_best_match(answer_set, question)
        if answer is not None:
            print(answer['q'] + ' ---> ' +answer['ans'])
            operator.click_trueorfalse(answer['ans'])
        else:
            print("No match found")
        time.sleep(time_delay)
    
def main():

    handler = WindowHandler()

    ocr = Ocr()
    
    handler.choose_window()
    handler.move_and_resize_window(1390,10,527,970)
    operator = WinOperator(handler.window)
    # handler.capture_screenshot()
    #遍历文件夹下所有文件，并返回文件路径
    results = []
    for root, dirs, files in os.walk("data"):
        for file in files:
            file_path = os.path.join(root, file)
            result = parse_json_lines(file_path)
            results.extend(result)
    time_delay = 0.5
    while True:
        
        screenshot_data = handler.capture_question_screenshot()
        #ocr
        question =''.join(ocr.do_ocr_ext(screenshot_data,simple=True))
        if len(question)==0: 
            time.sleep(time_delay)
            continue
        answer = find_best_match(results, question)
        if answer is not None:
            print(answer['q'] + ' ---> ' +answer['ans'])
            operator.click_trueorfalse(answer['ans'])
        else:
            print("No match found")
        time.sleep(time_delay)
        
if __name__ == "__main__":
    main()