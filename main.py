import time
from ocr import Ocr
from winoperator import WinOperator
from winhandler import WindowHandler
from fuzzywuzzy import process
import json
import os

def find_best_match(properties, query):
    names =[prop['q'] for prop in properties]
    best_match = process.extractOne(query,names)
    if best_match:
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


    
def main():

    handler = WindowHandler()
    # handler.select_screen_region()
    operator = WinOperator(handler.window)
    x1, y1, x2, y2 = operator.select_screen_region()
    ocr = Ocr()
    def find_and_click(text):
        search_results = ocr.search_text(query=text)
        if len(search_results)== 0: return False
        x,y= search_results[0]['position']['c']
        operator.click(x,y)
        return True
    

    
    #遍历文件夹下所有文件，并返回文件路径
    results = []
    for root, dirs, files in os.walk("data"):
        for file in files:
            file_path = os.path.join(root, file)
            result = parse_json_lines(file_path)
            results.extend(result)

    while True:
        screenshot_path = handler.capture_screenshot_ext(x1, y1, x2, y2, "screenshot.png")
        print(screenshot_path)
        # ocr.do_ocr(screenshot_path)
        # clock_head_p = ocr.multi_scale_template_match("screenshot.png","clock_head.png")
        # btn_confirm_p = ocr.multi_scale_template_match("screenshot.png","btn_confirm.png")
        # correct_icon_p = ocr.multi_scale_template_match("screenshot,png", "correct_icon.png")
        # incorrect_icon_p = ocr.multi_scale_template_match("screenshot.png", "incorrect_icon.png")

        # if btn_confirm_p: operator.click(btn_confirm_p[0], btn_confirm_p[1])
        # elif ocr.exists_text("答题"): find_and_click("答题")
        # elif clock_head_p:
        #     y= clock_head_p[1]
        #     ocr.crop_image("screenshot.png", "screenshot_2.png", x=0, y=(y-10) if (y-10)>0 else 10, width_ratio=1.0, height_ratio=0.1)
        question =''.join(ocr.do_ocr("screenshot.png",simple=True))
        answer = find_best_match(results, question)
        print(answer['q'] + ' ---> ' +answer['ans'])
        # if answer=='对'and correct_icon_p: operator.click(correct_icon_p[0], correct_icon_p[1])
        # elif answer=='错' and incorrect_icon_p: operator.click(incorrect_icon_p[0], incorrect_icon_p[1])
            
        time.sleep(1)
        
if __name__ == "__main__":
    main()