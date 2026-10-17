#!/bin/bash
echo "############ outputs/rc5 ############"
find /data/soffy/projects/hevi/outputs/rc5 -maxdepth 3 -type f 2>/dev/null | head -40
echo
echo "############ outputs/13-line-product-acceptance (top) ############"
ls -la /data/soffy/projects/hevi/outputs/13-line-product-acceptance/ 2>&1 | head -20
echo "--- artifacts ---"
ls -la /data/soffy/projects/hevi/outputs/13-line-product-acceptance/artifacts/ 2>&1 | head -40
echo
echo "############ output/hevi_v2 ############"
ls -la /data/soffy/projects/hevi/output/hevi_v2/ 2>&1 | head -20
echo
echo "############ output/real_content_chain ############"
find /data/soffy/projects/hevi/output/real_content_chain -maxdepth 2 -type f 2>/dev/null | head -30
echo
echo "############ data/cinematic_output ############"
find /data/soffy/projects/hevi/data/cinematic_output -maxdepth 2 2>/dev/null | head -30
