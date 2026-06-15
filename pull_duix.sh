#!/bin/bash
images=("guiji2025/fun-asr" "guiji2025/fish-speech-ziming" "guiji2025/duix.avatar")
for img in "${images[@]}"; do
    echo "Pulling $img..."
    until docker pull "$img"; do
        echo "Retry pulling $img..."
        sleep 5
    done
done
