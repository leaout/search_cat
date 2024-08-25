import time
from ocr import Ocr
from winoperator import WinOperator
from winhandler import WindowHandler
from fuzzywuzzy import process

def find_best_match(properties, query):
    names =[prop['name'] for prop in properties]
    best_match = process.extractOne(query,names)
    if best_match:
        best_name = best_match[0]
        for prop in properties:
            if prop['name'] == best_name:
                return prop['value']
    return None
    
    
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
    
    
    while True:
        screenshot_path = handler.capture_screenshot("screenshot.png")
        print(screenshot_path)
        ocr.do_ocr(screenshot_path)
        clock_head_p = ocr.multi_scale_template_match("screenshot.png","clock_head.png")
        btn_confirm_p = ocr.multi_scale_template_match("screenshot.png","btn_confirm.png")
        correct_icon_p = ocr.multi_scale_template_match("screenshot,png", "correct_icon.png")
        incorrect_icon_p = ocr.multi_scale_template_match("screenshot.png", "incorrect_icon.png")

        if btn_confirm_p: operator.click(btn_confirm_p[0], btn_confirm_p[1])
        elif ocr.exists_text("答题"): find_and_click("答题")
        elif clock_head_p:
            y= clock_head_p[1]
            ocr.crop_image("screenshot.png", "screenshot_2.png", x=0, y=(y-10) if (y-10)>0 else 10, width_ratio=1.0, height_ratio=0.1)
            question =''.join(ocr.do_ocr("screenshot 2.png",simple=True))
            answer = find_best_match(database.properties, question)
            print(f'{question} => {answer}')
            if answer=='对'and correct_icon_p: operator.click(correct_icon_p[0], correct_icon_p[1])
            elif answer=='错' and incorrect_icon_p: operator.click(incorrect_icon_p[0], incorrect_icon_p[1])
            
        time.sleep(1)
        
if __name__ == "__main__":
    main()