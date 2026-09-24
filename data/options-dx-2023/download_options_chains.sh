#!/bin/bash

# Download all 16 files in parallel with proper error handling
download_file() {
  local url="$1"
  local output="$2"
  echo "Starting: $output"
  curl -L -o "$output" -C - -w "\n%{filename_effective} -> %{http_code} (%{size_download} bytes)\n" "$url" 2>&1
}

# SPX Q1-Q4
download_file "https://www.optionsdx.com/?download_file=4818&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "SPX_2023_Q1.zip" &
download_file "https://www.optionsdx.com/?download_file=4819&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "SPX_2023_Q2.zip" &
download_file "https://www.optionsdx.com/?download_file=4820&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "SPX_2023_Q3.zip" &
download_file "https://www.optionsdx.com/?download_file=4821&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "SPX_2023_Q4.zip" &

# SPY Q1-Q4
download_file "https://www.optionsdx.com/?download_file=4822&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "SPY_2023_Q1.zip" &
download_file "https://www.optionsdx.com/?download_file=4823&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "SPY_2023_Q2.zip" &
download_file "https://www.optionsdx.com/?download_file=4824&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "SPY_2023_Q3.zip" &
download_file "https://www.optionsdx.com/?download_file=4825&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "SPY_2023_Q4.zip" &

# VIX Q1-Q4
download_file "https://www.optionsdx.com/?download_file=4826&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "VIX_2023_Q1.zip" &
download_file "https://www.optionsdx.com/?download_file=4827&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "VIX_2023_Q2.zip" &
download_file "https://www.optionsdx.com/?download_file=4828&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "VIX_2023_Q3.zip" &
download_file "https://www.optionsdx.com/?download_file=4829&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "VIX_2023_Q4.zip" &

# QQQ Q1-Q4
download_file "https://www.optionsdx.com/?download_file=4830&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "QQQ_2023_Q1.zip" &
download_file "https://www.optionsdx.com/?download_file=4831&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "QQQ_2023_Q2.zip" &
download_file "https://www.optionsdx.com/?download_file=4832&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "QQQ_2023_Q3.zip" &
download_file "https://www.optionsdx.com/?download_file=4833&order=wc_order_e4WhdQJRoTbSl&uid=8aa99b67693ed9e4a9e42bcd99be2655df5dd76558898c06c1ffb05f72de8f3e&key=e143742f-ff0f-4074-aa6d-63625494cbf3" "QQQ_2023_Q4.zip" &

wait
echo ""
echo "=== All downloads complete ==="
echo ""
ls -lh *.zip 2>/dev/null || echo "No ZIP files found"
