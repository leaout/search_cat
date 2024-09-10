from typing import Callable, Any, List, Tuple
import difflib
import cv2
from matplotlib import pyplot as plt
import csv
import json
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from paddleocr import PaddleOCR
import paddle

class Ocr:
    def __init__(self) -> None:
        self.ocr = PaddleOCR()
        self.data = None  # 存储OCR识别结果

    def multi_scale_template_match(self, main_image_path, template_image_path, method=cv2.TM_CCOEFF_NORMED, threshold=0.6, show=False):
        scales = [0.5, 0.75, 1.0, 1.25, 1.5]  # 定义要使用的尺度列表
        # 加载图像
        main_image = cv2.imread(main_image_path)
        template_image = cv2.imread(template_image_path)
        # 初始化变量以存储最佳匹配信息
        best_match = None
        best_val = -np.inf if method not in [cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED] else np.inf
        # 在多个尺度下进行匹配
        for scale in scales:
            scaled_template = cv2.resize(template_image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            # 拆分颜色通道
            main_b, main_g, main_r = cv2.split(main_image)
            template_b, template_g, template_r = cv2.split(scaled_template)
            # 对每个通道进行模板匹配
            result_b = cv2.matchTemplate(main_b, template_b, method)
            result_g = cv2.matchTemplate(main_g, template_g, method)
            result_r = cv2.matchTemplate(main_r, template_r, method)
            # 综合匹配结果
            result = (result_b + result_g + result_r) / 3
            # 确定当前尺度下的最佳匹配位置
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            if method in [cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED]:
                if min_val < best_val:
                    best_val = min_val
                    best_match = (scale, min_loc, scaled_template.shape[1], scaled_template.shape[0])
            else:
                if max_val > best_val:
                    best_val = max_val
                    best_match = (scale, max_loc, scaled_template.shape[1], scaled_template.shape[0])
        # 判断是否匹配成功
        match_successful = False
        if method in [cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED]:
            if best_val <= threshold: match_successful = True
        else:
            if best_val >= threshold: match_successful = True
        if not match_successful: return None
        # 在主图像上绘制最佳匹配位置
        scale, top_left, w, h = best_match
        bottom_right = (top_left[0] + w, top_left[1] + h)
        cv2.rectangle(main_image, top_left, bottom_right, (0, 255, 0), 2)
        # 显示结果
        if show:
            cv2.imshow('Multi-Scale Template Matching', main_image)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        return top_left[0], top_left[1], w, h

    def crop_image(self, file_path, output_path, x, y, width=None, height=None, width_ratio=None, height_ratio=None):
        """
        裁剪图片并保存结果。

        参数：
        - file_path: 输入图片的路径。
        - output_path: 裁剪后图片的保存路径。
        - x: 裁剪区域的左上角x坐标。
        - y: 裁剪区域的左上角y坐标。
        - width: 裁剪区域的宽度（可选）。
        - height: 裁剪区域的高度（可选）。
        - width_ratio: 裁剪区域宽度的比例（可选）。
        - height_ratio: 裁剪区域高度的比例（可选）。
        """
        image = cv2.imread(file_path)
        if image is None: return None
        img_height, img_width = image.shape[:2]
        if width_ratio is not None: width = int(img_width * width_ratio)
        if height_ratio is not None: height = int(img_height * height_ratio)
        if width is None or height is None: raise ValueError("请提供裁剪区域的宽度和高度，或者它们的比例。")
        crop_img = image[y:y+height, x:x+width]
        cv2.imwrite(output_path, crop_img)
        return output_path
        # 显示裁剪后的图片（可选）
        # cv2.imshow('Cropped Image', crop_img)
        # cv2.waitKey(0)
        # cv2.destroyAllWindows()
    
    def do_ocr(self, file_path: str, simple=False) -> List:
        """
        对图像文件进行OCR识别

        参数:
        file_path (str): 图像文件路径

        返回:
        List: OCR识别结果
        """
        data = self.ocr.ocr(file_path, cls=False)[0]
        if simple: return self.get_all_text(data)
        self.data = data
        return data
    
    def do_ocr_ext(self, img_data, simple=False) -> List:
        data = self.ocr.ocr(img_data, cls=False)[0]
        if simple: return self.get_all_text(data)
        self.data = data
        return data
    
    def search_text(self, query: str, data: List[List[Any]] = None, threshold: float = 0.6) -> List[Tuple[str, Any]]:
        """
        在OCR识别结果中搜索与query最相似的文本项，并按照相似度排序。

        参数:
        data (List[List[Any]]): OCR识别结果的数据。
        query (str): 要搜索的关键词。
        threshold (float): 相似度阈值，默认为0.6。

        返回:
        List[Tuple[str, Any]]: 按相似度排序的搜索结果列表，包含文本和相似度。
        """
        data = data if data else self.data
        results = []
        
        for item in data:
            points = [(int(x), int(y)) for x, y in item[0]]
            text, confidence = item[1]
            similarity = difflib.SequenceMatcher(None, query, text).ratio()
            if similarity >= threshold or query in text:
                results.append({'text': text, 
                                'similarity': similarity, 
                                'confidence':confidence, 
                                'position': {
                                    'p': points,
                                    'c': ((points[0][0]+points[1][0])/2, (points[0][1]+points[3][1])/2),
                                    'w': points[1][0]+points[0][0],
                                    'h': points[3][1]+points[0][1]
                                }})
        
        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results

    def exists_text(self, query: str, data: List[List[Any]] = None):
        return len(self.search_text(query, data=data)) > 0
    
    def filter_high_confidence(self, threshold: float = 0.9, data: List[List[Any]] = None) -> List[str]:
        """
        过滤高置信度的OCR结果

        参数:
        data (List[List[Any]]): OCR识别结果的数据。
        threshold (float): 置信度阈值，默认为0.9。

        返回:
        List[str]: 高置信度的识别结果文本列表
        """
        data = data if data else self.data
        return [item[1][0] for item in data if item[1][1] >= threshold]

    def export_to_file(self, file_path: str, file_format: str = 'json', data: List[List[Any]] = None) -> None:
        """
        将OCR结果导出到文件

        参数:
        data (List[List[Any]]): OCR识别结果的数据。
        file_path (str): 导出文件的路径。
        file_format (str): 文件格式，可以是'json'或'csv'。

        返回:
        None
        """
        data = data if data else self.data
        if file_format == 'json':
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        elif file_format == 'csv':
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Coordinates', 'Text', 'Confidence'])
                for item in data:
                    writer.writerow([item[0], item[1][0], item[1][1]])
        else:
            raise ValueError("Unsupported file format. Use 'json' or 'csv'.")

    def get_all_text(self, data: List[List[Any]] = None, position=False):
        """
        返回所有文本及其位置

        参数:
        data (List[List[Any]]): OCR识别结果的数据。

        返回:
        None
        """
        data = data if data else self.data
        res = []
        if data is None: return res
        for item in data:
            text = str(item[1][0])  # 确保 text 是字符串类型
            points = item[0]
            res.append((text, points) if position else text) 
        return res
              
    def display_text_positions(self, data: List[List[Any]] = None) -> None:
        """
        显示所有文本及其位置

        参数:
        data (List[List[Any]]): OCR识别结果的数据。

        返回:
        None
        """
        data = data if data else self.data
        for item in data:
            text = str(item[1][0])  # 确保 text 是字符串类型
            points = item[0]
            print(f"Text: {text}, Position: {points}")
            
    def visualize_results(self, file_path: str, show: bool = True, save_path: str = None, data: List[List[Any]] = None) -> None:
        """
        可视化OCR结果，在图像上绘制识别出的文本框

        参数:
        file_path (str): 图像文件路径。
        data (List[List[Any]]): OCR识别结果的数据。
        show (bool): 是否显示图像，默认值为True。
        save_path (str): 保存图像的路径，如果为None则不保存图像，默认值为None。

        返回:
        None
        """
        data = data if data else self.data
        # 读取图像并转换为PIL图像
        img = cv2.imread(file_path)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img)
        draw = ImageDraw.Draw(pil_img)
        # 使用黑体字体，可以选择合适的字体文件
        font = ImageFont.truetype("simhei.ttf", 20)  
        
        for item in data:
            points = item[0]
            # 确保 text 是字符串类型
            text = str(item[1][0])  
            # 确保 points 中的坐标是整数类型
            points = [(int(x), int(y)) for x, y in points]
            draw.polygon(points, outline=(0, 255, 0))
            draw.text((points[0][0], points[0][1] - 20), text, font=font, fill=(0, 255, 0))
        img = np.array(pil_img)
        if show:
            plt.imshow(img)
            plt.axis('off')
            plt.show()

        if save_path: pil_img.save(save_path)


if __name__ == "__main__":
    print(paddle.__version__)
    ocr = Ocr()
    data = ocr.do_ocr("D:/gitpro/qs_search/screenshot.jpg")
    ocr.display_text_positions()
    search_results = ocr.search_text(query="咸鱼")
    for item in search_results:
        print(f"Text: {item['text']}, Similarity: {item['similarity']:.2f}, Position: {item['position']}")
    ocr.visualize_results("D:/gitpro/qs_search/screenshot.jpg")
    
    # ocr.crop_image("screenshot.png", "screenshot_2.png", x=0, y=0, width_ratio=1.0, height_ratio=0.5)
    # print(ocr.do_ocr("screenshot_2.png", simple=True))