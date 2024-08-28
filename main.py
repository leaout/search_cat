import time
from ocr import Ocr
from winoperator import WinOperator
from winhandler import WindowHandler
from fuzzywuzzy import process
import json
def find_best_match(properties, query):
    names =[prop['q'] for prop in properties]
    best_match = process.extractOne(query,names)
    if best_match:
        best_name = best_match[0]
        for prop in properties:
            if prop['q'] == best_name:
                return prop['ans']
    return None


def parse_json_lines(file_path):
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
    ocr = Ocr()
    handler = WindowHandler()
    handler.choose_window()
    operator = WinOperator(handler.window)
    
    def find_and_click(text):
        search_results = ocr.search_text(query=text)
        if len(search_results)== 0: return False
        x,y= search_results[0]['position']['c']
        operator.click(x,y)
        return True
    

#     {"a":["对","错"],"ans":"A","q":"二郎神和四大天王奉命捉拿紫霞仙子?"}
# {"a":["对","错"],"ans":"B","q":"水帘洞原本叫盘丝洞，是青霞把名字改了"}
# {"a":["对","错"],"ans":"A","q":"盘丝洞原本叫水帘洞，是紫霞把名字改了"}
# {"a":["对","错"],"ans":"A","q":"至尊宝无意间拔出了紫霞的紫青宝剑?"}
    # 帮我实现打开文件，解析每一行数据是一个json，不是整个文件是json格式
    

    results = parse_json_lines("database.json")
    
    while True:
        screenshot_path = handler.capture_screenshot("screenshot.png")
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
        print(f'{question} => {answer}')
        # if answer=='对'and correct_icon_p: operator.click(correct_icon_p[0], correct_icon_p[1])
        # elif answer=='错' and incorrect_icon_p: operator.click(incorrect_icon_p[0], incorrect_icon_p[1])
            
        time.sleep(1)
        
if __name__ == "__main__":
    main()