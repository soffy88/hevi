from faster_whisper import WhisperModel
model = WhisperModel('/home/soffy/models/faster-whisper-large-v3-turbo', device='cpu', compute_type='int8')
segments, _ = model.transcribe('/data/soffy/projects/hevi-omrender/test.wav', word_timestamps=True, language='zh')
for segment in segments:
    for word in segment.words:
        print(f"'{word.word}' {word.start:.2f}-{word.end:.2f}")
