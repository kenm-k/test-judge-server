from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import docker
import tarfile
import io
import time

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = docker.from_env()

# === データモデルの定義 ===
class FileData(BaseModel):
    file: str
    code: str

class TestCase(BaseModel):
    name: str
    in_data: str
    out_data: Optional[str] = "" # outがない場合はカスタムチェッカー(受理スクリプト)想定

class JudgeRequest(BaseModel):
    language: str
    files: List[FileData]
    testcases: List[TestCase]
    time_limit: float = 2.0       # 制限時間 (秒)
    memory_limit: str = "256m"    # 制限メモリ

# === APIエンドポイント ===
@app.post("/api/judge")
async def judge_code(request: JudgeRequest):
    # 1. コンテナに送るための tar ファイルをメモリ上で作成
    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode='w') as tar:
        # 提出されたソースコードをtarに追加
        for f in request.files:
            file_data = f.code.encode('utf-8')
            info = tarfile.TarInfo(name=f.file)
            info.size = len(file_data)
            tar.addfile(info, io.BytesIO(file_data))
        
        # テストケースの入力データを "in/" ディレクトリ以下に展開するようにtarに追加
        for tc in request.testcases:
            in_data = tc.in_data.encode('utf-8')
            info = tarfile.TarInfo(name=f"in/{tc.name}")
            info.size = len(in_data)
            tar.addfile(info, io.BytesIO(in_data))
            
    tar_stream.seek(0)

    # 2. 実行用コンテナを「待機状態」で起動 (tail -f /dev/null で死なないようにする)
    container = client.containers.create(
        image="my-judge-runner:latest",
        command="tail -f /dev/null", 
        detach=True,
        mem_limit=request.memory_limit, # ここでメモリ制限を適用
        network_mode="none"
    )

    try:
        container.start()
        # tar(ソースコード群 + inフォルダ) をコンテナ内の /workspace に配置
        container.put_archive("/workspace", tar_stream)

        # 3. コンパイルの実行
        # exec_runではワイルドカード(*.cpp)が自動展開されないため、明示的にファイル名を結合してコマンドを作成します
        cpp_files = [f.file for f in request.files if f.file.endswith(".cpp")]
        if not cpp_files:
            return {
                "status": "CE",
                "message": "コンパイル可能な .cpp ファイルが見つかりません",
                "results": [],
                "compile_log": ""
            }
            
        # ファイル名をスペース区切りで結合 (例: g++ -O2 -std=c++17 main.cpp Point.cpp -o a.out)
        compile_cmd = f"g++ -O2 -std=c++17 {' '.join(cpp_files)} -o a.out"
        
        # workdirを明示的に指定して実行
        compile_exit, compile_out = container.exec_run(compile_cmd, workdir="/workspace")
        if compile_exit != 0:
            return {
                "status": "CE",
                "message": "コンパイルエラー",
                "results": [],
                "compile_log": compile_out.decode('utf-8', errors='replace')
            }

        # 4. 各テストケースの逐次実行
        results = []
        all_ac = True

        for tc in request.testcases:
            case_name = tc.name
            
            # Linuxの timeout コマンドを使って、制限時間付きで実行
            # 例: timeout 2.0 bash -c './a.out < in/case1.txt'
            run_cmd = f"timeout {request.time_limit} bash -c './a.out < in/{case_name}'"
            
            start_time = time.time()
            # 実行時も workdir を明示
            run_exit, run_out = container.exec_run(run_cmd, workdir="/workspace")
            exec_time = time.time() - start_time
            
            actual_output = run_out.decode('utf-8', errors='replace')
            case_status = ""

            # 終了コードの判定
            if run_exit == 124:
                # timeout コマンドがタイムアウトで終了した時の終了コードは 124
                case_status = "TLE"
                all_ac = False
            elif run_exit != 0:
                # セグフォ等の実行時エラー
                case_status = "RE"
                all_ac = False
            else:
                # 正常終了した場合、想定解と比較する
                if tc.out_data:
                    # 通常の完全一致比較 (末尾の空白や改行を無視)
                    if actual_output.strip() == tc.out_data.strip():
                        case_status = "AC"
                    else:
                        case_status = "WA"
                        all_ac = False
                else:
                    # TODO: out_dataが空の場合（受理スクリプトでの判定）
                    # 例: container.exec_run(f"./checker in/{case_name} actual_out.txt") を実行して結果を見る
                    case_status = "AC (Custom Checked)" 

            # ケースごとの結果を保存
            results.append({
                "case_name": case_name,
                "status": case_status,
                "time": round(exec_time, 3),
                "output": actual_output
            })

        # 5. 全体の結果をまとめる
        final_status = "AC" if all_ac else "WA/TLE/RE" # 詳細な集計はフロントで行う
        
        return {
            "status": final_status,
            "message": "",
            "results": results,
            "compile_log": ""
        }

    except Exception as e:
        return {"status": "ERROR", "message": str(e), "results": []}
    
    finally:
        # 6. 使い終わったコンテナを強制削除
        container.remove(force=True)
