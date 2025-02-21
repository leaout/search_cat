import speech_recognition as sr
from langchain.chains import ConversationChain
from langchain.llms import OpenAI
import threading
import queue

class AudioProcessor:
    def __init__(self, api_key):
        self.recognizer = sr.Recognizer()
        self.mic = sr.Microphone()
        self.audio_queue = queue.Queue()
        self.running = False
        self.llm = OpenAI(api_key=api_key)
        self.conversation = ConversationChain(llm=self.llm)
        
    def start_listening(self):
        self.running = True
        threading.Thread(target=self._listen_loop, daemon=True).start()
        
    def stop_listening(self):
        self.running = False
        
    def _listen_loop(self):
        with self.mic as source:
            self.recognizer.adjust_for_ambient_noise(source)
            while self.running:
                try:
                    print("Listening...")
                    audio = self.recognizer.listen(source, phrase_time_limit=5)
                    self.audio_queue.put(audio)
                except sr.WaitTimeoutError:
                    continue
                    
    def process_audio(self):
        if not self.audio_queue.empty():
            audio = self.audio_queue.get()
            try:
                text = self.recognizer.recognize_google(audio, language="zh-CN")
                response = self.conversation.predict(input=text)
                return text, response
            except sr.UnknownValueError:
                return None, "无法识别语音"
            except sr.RequestError:
                return None, "语音识别服务不可用"
        return None, None

def create_audio_processor(api_key):
    return AudioProcessor(api_key)
