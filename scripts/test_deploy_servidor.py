"""Valida o lançador com repositórios Git locais e um deploy fictício, sem servidor."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(os.name == 'nt', 'Ensaio do lançador Windows')
class DeployLauncherTests(unittest.TestCase):
    def setUp(self):
        self.artifacts = (PROJECT / 'logs').resolve()
        self.artifacts.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='deploy_fixture_', dir=self.artifacts)
        self.base = Path(self.temporary.name).resolve()
        self.addCleanup(self.limpar_fixture)
        self.repo = self.base / 'repositorio com espacos'
        (self.repo / 'scripts').mkdir(parents=True)
        shutil.copyfile(PROJECT / 'executar_deploy_servidor.bat', self.repo / 'executar_deploy_servidor.bat')
        shutil.copyfile(PROJECT / 'scripts/deploy_servidor.ps1', self.repo / 'scripts/deploy_servidor.ps1')
        # Não copia o projeto ou o deploy real. Só este stub pode ser executado.
        (self.repo / 'scripts/deploy_production.ps1').write_text('''param([switch]$CheckOnly, [switch]$DryRun, [switch]$SkipCaldeiraWarmup)
$Mode = if ($CheckOnly) { 'check' } elseif ($DryRun) { 'dry' } else { 'real' }
Set-Content -LiteralPath (Join-Path $PSScriptRoot '..\\deploy_called.txt') -Value "$Mode|$SkipCaldeiraWarmup"
if ($env:DEPLOY_STUB_RESULT) { exit ([int]$env:DEPLOY_STUB_RESULT) }
exit 0
''', encoding='ascii')
        (self.repo / 'version.txt').write_text('v1', encoding='ascii')
        self.git('init', '-b', 'main')
        self.identidade(self.repo)
        self.git('add', '.')
        self.git('-c', 'commit.gpgsign=false', 'commit', '-m', 'Fixture inicial')
        self.remote = self.base / 'origin.git'
        self.git('init', '--bare', '-b', 'main', str(self.remote))
        self.git('remote', 'add', 'origin', str(self.remote))
        self.git('push', '-u', 'origin', 'main')

    def limpar_fixture(self):
        # Verifica o alvo absoluto antes da remoção recursiva do diretório temporário.
        self.base.resolve().relative_to(self.artifacts)
        self.temporary.cleanup()

    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd or self.repo, capture_output=True,
                              text=True, encoding='utf-8', errors='replace', check=True, timeout=30)

    def identidade(self, path):
        self.git('config', 'user.name', 'Teste Deploy', cwd=path)
        self.git('config', 'user.email', 'deploy@example.test', cwd=path)
        self.git('config', 'core.autocrlf', 'false', cwd=path)

    def executar(self, *flags, failure=None):
        env = os.environ.copy()
        env.pop('DEPLOY_STUB_RESULT', None)
        if failure:
            env['DEPLOY_STUB_RESULT'] = str(failure)
        # Nome relativo fixo: a própria fixture contém espaços no caminho.
        command = 'call executar_deploy_servidor.bat' + ''.join(' ' + flag for flag in flags)
        return subprocess.run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', command],
                              cwd=self.repo, input='\n', capture_output=True, text=True,
                              encoding='utf-8', errors='replace', env=env, timeout=45)

    def assert_sem_deploy(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.repo / 'deploy_called.txt').exists())
        self.assertNotIn('[CONCLUIDO]', result.stdout)

    def test_pull_atualiza_o_proprio_bat_e_executa_deploy(self):
        publisher = self.base / 'publisher'
        self.git('clone', str(self.remote), str(publisher))
        self.identidade(publisher)
        (publisher / 'version.txt').write_text('v2', encoding='ascii')
        bat = publisher / 'executar_deploy_servidor.bat'
        bat.write_text('@rem Versao atualizada durante o pull\n' + bat.read_text(encoding='ascii'), encoding='ascii')
        self.git('add', '.', cwd=publisher)
        self.git('-c', 'commit.gpgsign=false', 'commit', '-m', 'Atualizacao da fixture', cwd=publisher)
        self.git('push', 'origin', 'main', cwd=publisher)
        result = self.executar('-SkipCaldeiraWarmup')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.repo / 'version.txt').read_text(), 'v2')
        self.assertIn('real|True', (self.repo / 'deploy_called.txt').read_text())
        self.assertIn('[CONCLUIDO]', result.stdout)

    def test_falha_no_pull_interrompe_antes_do_deploy(self):
        self.git('remote', 'set-url', 'origin', str(self.base / 'nao_existe.git'))
        self.assert_sem_deploy(self.executar())

    def test_alteracao_local_e_preservada_sem_deploy(self):
        (self.repo / 'version.txt').write_text('alteracao local', encoding='ascii')
        self.assert_sem_deploy(self.executar())
        self.assertEqual((self.repo / 'version.txt').read_text(), 'alteracao local')

    def test_branch_diferente_nao_e_modificada(self):
        self.git('checkout', '-b', 'desenvolvimento')
        self.assert_sem_deploy(self.executar())
        self.assertEqual(self.git('branch', '--show-current').stdout.strip(), 'desenvolvimento')

    def test_diagnostico_nao_executa_pull(self):
        self.git('remote', 'set-url', 'origin', str(self.base / 'nao_existe.git'))
        (self.repo / 'version.txt').write_text('alteracao local', encoding='ascii')
        for flag, mode in [('-CheckOnly', 'check'), ('-DryRun', 'dry')]:
            with self.subTest(flag=flag):
                result = self.executar(flag)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(mode, (self.repo / 'deploy_called.txt').read_text())
                self.assertEqual((self.repo / 'version.txt').read_text(), 'alteracao local')

    def test_falha_do_script_mestre_nao_exibe_sucesso(self):
        result = self.executar(failure=2)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.repo / 'deploy_called.txt').exists())
        self.assertNotIn('[CONCLUIDO]', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
