"""Small moving synthetic video with Portuguese speech; no external media."""
from pathlib import Path
import subprocess


def generate(target: Path):
    speech = target.with_suffix('.wav')
    text = ('Este é um vídeo de teste do projeto ShortForge. Vamos criar um vídeo vertical com áudio e legendas em português. '
            'A ferramenta seleciona um trecho, renderiza o vídeo e permite baixar o resultado com segurança. ')*5
    subprocess.run(['espeak','-v','pt-br','-s','145','-w',str(speech),text],check=True,timeout=20)
    subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=30',
                    '-i',str(speech),'-t','30','-c:v','libx264','-threads','2','-preset','ultrafast',
                    '-pix_fmt','yuv420p','-c:a','aac','-b:a','64k',str(target)],check=True,timeout=60)
    speech.unlink()
