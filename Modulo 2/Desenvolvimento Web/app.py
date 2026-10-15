from flask import (
    Flask,
    request,
    redirect,
    url_for,
    session,
    flash,
    render_template_string,
    g
)

import sqlite3
import os
from functools import wraps

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)


# ============================================================
# CONFIGURAÇÃO
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "chave-secreta-do-taskflow-troque-em-producao"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BANCO = os.path.join(
    BASE_DIR,
    "taskflow.db"
)

MAX_PERFIS = 5


# ============================================================
# AVATARES
# ============================================================

AVATARES = [
    "😀", "😎", "🤓", "😃", "😁", "😆",
    "😂", "🤣", "😊", "🥰", "😍", "🤩",
    "😜", "🤪", "😇", "🤠", "🥳", "😺",
    "😸", "😹", "😻", "😼", "😽", "🙀",
    "🐱", "🐶", "🐼", "🐨", "🐯", "🦁",
    "🐻", "🐰", "🐲", "🦄", "🚀", "⭐",
    "🔥", "⚡", "🎮", "🎯", "🏆", "💎"
]


PRIORIDADES = {
    "baixa": {
        "nome": "Baixa",
        "cor": "#22c55e",
        "emoji": "🟢"
    },

    "media": {
        "nome": "Média",
        "cor": "#f59e0b",
        "emoji": "🟡"
    },

    "alta": {
        "nome": "Alta",
        "cor": "#ef4444",
        "emoji": "🔴"
    }
}


# ============================================================
# BANCO DE DADOS
# ============================================================

def conectar():

    conexao = sqlite3.connect(
        BANCO,
        timeout=15,
        check_same_thread=False
    )

    conexao.row_factory = sqlite3.Row

    # Ajuda o SQLite a lidar melhor com leitura/escrita.
    conexao.execute("PRAGMA foreign_keys = ON")
    conexao.execute("PRAGMA busy_timeout = 15000")
    conexao.execute("PRAGMA journal_mode = WAL")

    return conexao


def get_db():

    if "db" not in g:
        g.db = conectar()

    return g.db


@app.teardown_appcontext
def fechar_banco(exception=None):

    db = g.pop("db", None)

    if db is not None:
        db.close()


# ============================================================
# UTILITÁRIOS DO BANCO
# ============================================================

def colunas_tabela(db, tabela):

    resultado = db.execute(
        f"PRAGMA table_info({tabela})"
    ).fetchall()

    return {
        coluna["name"]
        for coluna in resultado
    }


def adicionar_coluna_se_nao_existir(
    db,
    tabela,
    coluna,
    definicao
):

    colunas = colunas_tabela(
        db,
        tabela
    )

    if coluna not in colunas:

        db.execute(
            f"""
            ALTER TABLE {tabela}
            ADD COLUMN {coluna} {definicao}
            """
        )


# ============================================================
# CRIAÇÃO / MIGRAÇÃO DO BANCO
# ============================================================

def criar_banco():

    db = conectar()

    try:

        # ----------------------------------------------------
        # USUÁRIOS
        # ----------------------------------------------------

        db.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                nome TEXT NOT NULL,

                email TEXT NOT NULL UNIQUE,

                senha TEXT NOT NULL,

                criado_em TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)


        # ----------------------------------------------------
        # PERFIS
        # ----------------------------------------------------

        db.execute("""
            CREATE TABLE IF NOT EXISTS perfis (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                usuario_id INTEGER NOT NULL,

                nome TEXT NOT NULL,

                avatar TEXT NOT NULL DEFAULT '😀',

                criado_em TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (usuario_id)
                    REFERENCES usuarios(id)
                    ON DELETE CASCADE
            )
        """)


        # Caso exista uma tabela de perfis antiga,
        # garante as colunas importantes.

        adicionar_coluna_se_nao_existir(
            db,
            "perfis",
            "nome",
            "TEXT NOT NULL DEFAULT 'Perfil'"
        )

        adicionar_coluna_se_nao_existir(
            db,
            "perfis",
            "avatar",
            "TEXT NOT NULL DEFAULT '😀'"
        )


        # ----------------------------------------------------
        # TAREFAS
        # ----------------------------------------------------

        db.execute("""
            CREATE TABLE IF NOT EXISTS tarefas (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                usuario_id INTEGER NOT NULL,

                perfil_id INTEGER,

                titulo TEXT NOT NULL,

                concluida INTEGER
                    DEFAULT 0,

                data_vencimento TEXT,

                prioridade TEXT
                    DEFAULT 'media',

                criado_em TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,

                atualizado_em TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (usuario_id)
                    REFERENCES usuarios(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (perfil_id)
                    REFERENCES perfis(id)
                    ON DELETE CASCADE
            )
        """)


        # ----------------------------------------------------
        # MIGRAÇÃO DE BANCO ANTIGO
        # ----------------------------------------------------

        # Isso resolve o erro:
        #
        # sqlite3.OperationalError:
        # no such column: perfil_id
        #
        # Se a sua tabela tarefas já existia, adicionamos
        # as novas colunas sem apagar as tarefas.

        adicionar_coluna_se_nao_existir(
            db,
            "tarefas",
            "perfil_id",
            "INTEGER"
        )

        adicionar_coluna_se_nao_existir(
            db,
            "tarefas",
            "data_vencimento",
            "TEXT"
        )

        adicionar_coluna_se_nao_existir(
            db,
            "tarefas",
            "prioridade",
            "TEXT DEFAULT 'media'"
        )

        adicionar_coluna_se_nao_existir(
            db,
            "tarefas",
            "atualizado_em",
            "TIMESTAMP"
        )


        # ----------------------------------------------------
        # CRIAR PERFIL PADRÃO PARA USUÁRIOS ANTIGOS
        # ----------------------------------------------------

        usuarios = db.execute("""
            SELECT id, nome
            FROM usuarios
        """).fetchall()


        for usuario in usuarios:

            quantidade = db.execute(
                """
                SELECT COUNT(*) AS total
                FROM perfis
                WHERE usuario_id = ?
                """,
                (usuario["id"],)
            ).fetchone()["total"]


            if quantidade == 0:

                cursor = db.execute(
                    """
                    INSERT INTO perfis
                        (usuario_id, nome, avatar)
                    VALUES
                        (?, ?, ?)
                    """,
                    (
                        usuario["id"],
                        usuario["nome"],
                        "😀"
                    )
                )

                perfil_id = cursor.lastrowid

                # Coloca as tarefas antigas desse usuário
                # dentro do novo perfil.

                db.execute(
                    """
                    UPDATE tarefas

                    SET perfil_id = ?

                    WHERE usuario_id = ?

                    AND (
                        perfil_id IS NULL
                        OR perfil_id = 0
                    )
                    """,
                    (
                        perfil_id,
                        usuario["id"]
                    )
                )


        # ----------------------------------------------------
        # GARANTE VALORES PADRÃO
        # ----------------------------------------------------

        db.execute("""
            UPDATE tarefas

            SET prioridade = 'media'

            WHERE prioridade IS NULL

            OR prioridade = ''
        """)


        db.execute("""
            UPDATE tarefas

            SET atualizado_em = CURRENT_TIMESTAMP

            WHERE atualizado_em IS NULL
        """)


        # Índices ajudam as buscas por perfil.

        db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_perfis_usuario
            ON perfis(usuario_id)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_tarefas_perfil
            ON tarefas(perfil_id)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_tarefas_usuario
            ON tarefas(usuario_id)
        """)


        db.commit()

    finally:

        db.close()


# ============================================================
# USUÁRIO
# ============================================================

def usuario_logado():

    return "usuario_id" in session


def usuario_id():

    return session.get("usuario_id")


def perfil_id():

    return session.get("perfil_id")


def exigir_login(funcao):

    @wraps(funcao)
    def wrapper(*args, **kwargs):

        if not usuario_logado():

            return redirect(
                url_for("login")
            )

        return funcao(
            *args,
            **kwargs
        )

    return wrapper


def exigir_perfil(funcao):

    @wraps(funcao)
    def wrapper(*args, **kwargs):

        if not usuario_logado():

            return redirect(
                url_for("login")
            )

        if not perfil_id():

            return redirect(
                url_for("perfis")
            )

        # Verifica se o perfil pertence ao usuário.

        db = get_db()

        perfil = db.execute(
            """
            SELECT id

            FROM perfis

            WHERE id = ?

            AND usuario_id = ?
            """,
            (
                perfil_id(),
                usuario_id()
            )
        ).fetchone()


        if not perfil:

            session.pop(
                "perfil_id",
                None
            )

            return redirect(
                url_for("perfis")
            )


        return funcao(
            *args,
            **kwargs
        )

    return wrapper


# ============================================================
# TEMPLATE BASE
# ============================================================

CSS = """
<style>

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {

    font-family:
        Arial,
        Helvetica,
        sans-serif;

    background:
        linear-gradient(
            135deg,
            #020617,
            #0f172a
        );

    color: #e2e8f0;

    min-height: 100vh;
}


/* ==========================================================
   NAVBAR
========================================================== */

.navbar {

    background: #020617;

    border-bottom:
        1px solid #1e293b;

    position: sticky;

    top: 0;

    z-index: 10;
}

.navbar-content {

    max-width: 1100px;

    margin: auto;

    padding:
        14px 20px;

    display: flex;

    align-items: center;

    justify-content: space-between;

    gap: 20px;
}

.logo {

    color: #38bdf8;

    font-size: 25px;

    font-weight: bold;

    text-decoration: none;
}

.nav-links {

    display: flex;

    align-items: center;

    gap: 15px;

    flex-wrap: wrap;
}

.nav-links a {

    color: #cbd5e1;

    text-decoration: none;
}

.nav-links a:hover {

    color: #38bdf8;
}

.usuario-nav {

    color: #e2e8f0;

    display: flex;

    align-items: center;

    gap: 7px;
}


/* ==========================================================
   CONTAINER
========================================================== */

.container {

    max-width: 1050px;

    margin: auto;

    padding:
        35px 20px 60px;
}


/* ==========================================================
   CARDS
========================================================== */

.card {

    background: #1e293b;

    border:
        1px solid #334155;

    border-radius: 18px;

    padding: 25px;

    box-shadow:
        0 15px 40px rgba(0,0,0,.18);
}


/* ==========================================================
   BOTÕES
========================================================== */

.btn {

    display: inline-flex;

    align-items: center;

    justify-content: center;

    gap: 6px;

    border: none;

    border-radius: 9px;

    padding: 10px 15px;

    color: white;

    font-weight: bold;

    cursor: pointer;

    text-decoration: none;

    transition: .2s;
}

.btn:hover {

    transform: translateY(-1px);
}

.btn-primary {

    background: #0ea5e9;
}

.btn-primary:hover {

    background: #0284c7;
}

.btn-success {

    background: #16a34a;
}

.btn-danger {

    background: #dc2626;
}

.btn-warning {

    background: #d97706;
}

.btn-secondary {

    background: #334155;
}

.btn-secondary:hover {

    background: #475569;
}


/* ==========================================================
   VOLTAR
========================================================== */

.btn-voltar {

    display: inline-flex;

    align-items: center;

    gap: 8px;

    margin-bottom: 25px;

    padding: 10px 16px;

    background: #1e293b;

    color: #cbd5e1;

    border:
        1px solid #334155;

    border-radius: 9px;

    text-decoration: none;

    font-weight: bold;

    transition: .2s;
}

.btn-voltar:hover {

    background: #334155;

    color: white;

    transform:
        translateX(-3px);
}


/* ==========================================================
   FLASH
========================================================== */

.flash {

    padding: 14px 18px;

    margin-bottom: 20px;

    border-radius: 10px;

    background: #334155;
}

.flash.sucesso {

    background: #166534;
}

.flash.erro {

    background: #7f1d1d;
}


/* ==========================================================
   AUTH
========================================================== */

.auth-container {

    max-width: 430px;

    margin:
        55px auto;
}

.auth-card {

    background: #1e293b;

    border:
        1px solid #334155;

    border-radius: 18px;

    padding: 35px;

    box-shadow:
        0 25px 70px rgba(0,0,0,.35);
}

.auth-card h1 {

    color: #38bdf8;

    text-align: center;

    margin-bottom: 10px;
}

.descricao {

    color: #94a3b8;

    text-align: center;

    margin-bottom: 25px;
}

.form-group {

    margin-bottom: 18px;
}

.form-group label {

    display: block;

    margin-bottom: 7px;

    color: #cbd5e1;

    font-weight: bold;
}

input,
select {

    width: 100%;

    padding: 12px 14px;

    border:
        1px solid #334155;

    border-radius: 9px;

    background: #0f172a;

    color: white;

    outline: none;

    font-size: 15px;
}

input:focus,
select:focus {

    border-color: #38bdf8;
}

.auth-button {

    width: 100%;

    margin-top: 5px;
}

.auth-link {

    text-align: center;

    margin-top: 20px;

    color: #94a3b8;
}

.auth-link a {

    color: #38bdf8;
}


/* ==========================================================
   TÍTULOS
========================================================== */

.page-title {

    margin-bottom: 25px;
}

.page-title h1 {

    font-size: 34px;

    margin-bottom: 7px;
}

.page-title p {

    color: #94a3b8;
}


/* ==========================================================
   PERFIS
========================================================== */

.perfis-header {

    text-align: center;

    margin-bottom: 30px;
}

.perfis-header h1 {

    font-size: 34px;

    margin-bottom: 8px;
}

.perfis-header p {

    color: #94a3b8;
}

.perfis-grid {

    display: grid;

    grid-template-columns:
        repeat(4, 1fr);

    gap: 18px;
}

.perfil-card {

    position: relative;

    background: #1e293b;

    border:
        2px solid #334155;

    border-radius: 16px;

    padding: 25px 15px;

    text-align: center;

    color: white;

    text-decoration: none;

    transition: .2s;
}

.perfil-card:hover {

    border-color: #38bdf8;

    transform:
        translateY(-5px);
}

.perfil-card.atual {

    border-color: #22c55e;

    background:
        #132e2a;
}

.perfil-avatar {

    width: 90px;

    height: 90px;

    margin:
        0 auto 15px;

    display: flex;

    align-items: center;

    justify-content: center;

    border-radius: 50%;

    background: #0f172a;

    font-size: 52px;
}

.perfil-card strong {

    display: block;

    font-size: 18px;

    margin-bottom: 6px;
}

.perfil-card span {

    color: #94a3b8;

    font-size: 13px;
}

.novo-perfil {

    color: #38bdf8;
}

.novo-perfil .perfil-avatar {

    color: #38bdf8;

    font-size: 45px;
}


/* ==========================================================
   PERFIL
========================================================== */

.perfil-topo {

    display: flex;

    align-items: center;

    gap: 25px;

    margin-bottom: 30px;
}

.perfil-topo-avatar {

    width: 100px;

    height: 100px;

    border-radius: 50%;

    display: flex;

    align-items: center;

    justify-content: center;

    font-size: 58px;

    background: #0f172a;
}

.perfil-topo h1 {

    font-size: 34px;

    margin-bottom: 5px;
}

.perfil-topo p {

    color: #94a3b8;
}

.progresso-mini {

    margin-top: 8px;

    color: #38bdf8;
}


/* ==========================================================
   AVATARES
========================================================== */

.avatar-section {

    margin-top: 25px;
}

.avatar-section h2 {

    margin-bottom: 7px;
}

.avatar-section > p {

    color: #94a3b8;

    margin-bottom: 20px;
}

.avatar-grid {

    display: grid;

    grid-template-columns:
        repeat(6, 1fr);

    gap: 10px;
}

.avatar-option {

    border:
        2px solid #334155;

    background: #0f172a;

    border-radius: 10px;

    padding: 12px;

    font-size: 28px;

    cursor: pointer;

    transition: .15s;
}

.avatar-option:hover {

    border-color: #38bdf8;

    transform:
        scale(1.04);
}

.avatar-option.selecionado {

    border-color: #22c55e;

    background: #164e3b;
}


/* ==========================================================
   ESCOLHER PERFIL
========================================================== */

.escolher-perfil {

    margin-top: 30px;
}

.escolher-perfil h2 {

    margin-bottom: 7px;
}

.escolher-perfil > p {

    color: #94a3b8;

    margin-bottom: 20px;
}


/* ==========================================================
   DASHBOARD
========================================================== */

.dashboard-header {

    display: flex;

    align-items: center;

    justify-content: space-between;

    gap: 20px;

    margin-bottom: 25px;
}

.dashboard-header h1 {

    font-size: 34px;

    margin-bottom: 6px;
}

.dashboard-header p {

    color: #94a3b8;
}

.perfil-atual {

    display: flex;

    align-items: center;

    gap: 10px;

    background: #1e293b;

    padding: 10px 14px;

    border-radius: 12px;

    text-decoration: none;

    color: white;
}

.perfil-atual .avatar {

    font-size: 27px;
}


/* ==========================================================
   PROGRESSO
========================================================== */

.progresso-card {

    background: #1e293b;

    border:
        1px solid #334155;

    border-radius: 15px;

    padding: 20px;

    margin-bottom: 25px;
}

.progresso-header {

    display: flex;

    justify-content: space-between;

    margin-bottom: 10px;
}

.progresso-header span:last-child {

    color: #38bdf8;

    font-weight: bold;
}

.barra {

    width: 100%;

    height: 13px;

    background: #0f172a;

    border-radius: 20px;

    overflow: hidden;
}

.barra-progresso {

    height: 100%;

    background:
        linear-gradient(
            90deg,
            #0ea5e9,
            #22c55e
        );

    border-radius: 20px;

    transition: .3s;
}


/* ==========================================================
   ESTATÍSTICAS
========================================================== */

.estatisticas {

    display: grid;

    grid-template-columns:
        repeat(4, 1fr);

    gap: 14px;

    margin-bottom: 25px;
}

.stat {

    background: #1e293b;

    border:
        1px solid #334155;

    border-radius: 13px;

    padding: 20px;

    text-align: center;
}

.stat .numero {

    display: block;

    font-size: 29px;

    color: #38bdf8;

    font-weight: bold;

    margin-bottom: 5px;
}

.stat .label {

    color: #94a3b8;
}


/* ==========================================================
   NOVA TAREFA
========================================================== */

.nova-tarefa {

    background: #1e293b;

    border:
        1px solid #334155;

    border-radius: 15px;

    padding: 20px;

    margin-bottom: 20px;
}

.nova-grid {

    display: grid;

    grid-template-columns:
        2fr 1fr 1fr auto;

    gap: 10px;
}


/* ==========================================================
   FILTROS
========================================================== */

.filtros {

    display: flex;

    gap: 9px;

    flex-wrap: wrap;

    margin-bottom: 20px;
}

.filtro {

    padding: 8px 14px;

    border-radius: 8px;

    text-decoration: none;

    color: #cbd5e1;

    background: #1e293b;

    border:
        1px solid #334155;
}

.filtro.ativo {

    background: #38bdf8;

    color: #082f49;

    border-color: #38bdf8;

    font-weight: bold;
}


/* ==========================================================
   TAREFA
========================================================== */

.tarefa {

    background: #1e293b;

    border:
        1px solid #334155;

    border-left:
        5px solid #f59e0b;

    border-radius: 13px;

    padding: 18px;

    margin-bottom: 12px;

    display: flex;

    justify-content: space-between;

    align-items: center;

    gap: 15px;
}

.tarefa.alta {

    border-left-color: #ef4444;
}

.tarefa.media {

    border-left-color: #f59e0b;
}

.tarefa.baixa {

    border-left-color: #22c55e;
}

.tarefa.concluida {

    opacity: .65;

    border-left-color: #22c55e;
}

.tarefa.concluida h3 {

    text-decoration: line-through;

    color: #94a3b8;
}

.tarefa h3 {

    margin-bottom: 8px;

    word-break: break-word;
}

.tarefa-meta {

    display: flex;

    flex-wrap: wrap;

    gap: 8px;
}

.badge {

    padding: 5px 9px;

    border-radius: 7px;

    font-size: 12px;

    background: #0f172a;

    color: #cbd5e1;
}

.badge.atrasada {

    background: #7f1d1d;

    color: #fecaca;
}

.acoes {

    display: flex;

    gap: 7px;

    flex-shrink: 0;
}

.acoes form {

    display: inline;
}


/* ==========================================================
   VAZIO
========================================================== */

.vazio {

    text-align: center;

    padding: 50px;

    background: #1e293b;

    border-radius: 15px;

    color: #64748b;
}


/* ==========================================================
   FOOTER
========================================================== */

footer {

    text-align: center;

    color: #475569;

    padding:
        30px 20px 40px;
}


/* ==========================================================
   RESPONSIVO
========================================================== */

@media (max-width: 850px) {

    .perfis-grid {

        grid-template-columns:
            repeat(2, 1fr);
    }

    .estatisticas {

        grid-template-columns:
            repeat(2, 1fr);
    }

    .nova-grid {

        grid-template-columns:
            1fr 1fr;
    }

    .avatar-grid {

        grid-template-columns:
            repeat(5, 1fr);
    }

}


@media (max-width: 600px) {

    .navbar-content {

        flex-direction: column;
    }

    .dashboard-header {

        flex-direction: column;

        align-items: flex-start;
    }

    .tarefa {

        flex-direction: column;

        align-items: flex-start;
    }

    .acoes {

        width: 100%;
    }

    .acoes .btn {

        flex: 1;
    }

    .nova-grid {

        grid-template-columns: 1fr;
    }

    .perfil-topo {

        flex-direction: column;

        align-items: flex-start;
    }

    .avatar-grid {

        grid-template-columns:
            repeat(4, 1fr);
    }

}


@media (max-width: 400px) {

    .perfis-grid {

        grid-template-columns: 1fr;
    }

    .estatisticas {

        grid-template-columns: 1fr;
    }

    .avatar-grid {

        grid-template-columns:
            repeat(3, 1fr);
    }

}

</style>
"""


BASE_HTML = """
<!DOCTYPE html>

<html lang="pt-BR">

<head>

    <meta charset="UTF-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0"
    >

    <title>{{ titulo }} - TaskFlow</title>

    {{ css|safe }}

</head>

<body>

<nav class="navbar">

    <div class="navbar-content">

        <a
            href="{{ url_for('inicio') if session.get('perfil_id') else url_for('perfis') }}"
            class="logo"
        >
            TaskFlow
        </a>


        {% if session.get('usuario_id') %}

        <div class="nav-links">

            {% if session.get('perfil_id') %}

            <a
                href="{{ url_for('perfis') }}"
                class="usuario-nav"
            >
                🔄 Trocar perfil
            </a>

            <a
                href="{{ url_for('perfil') }}"
                class="usuario-nav"
            >
                👤 Perfil
            </a>

            {% endif %}

            <a
                href="{{ url_for('logout') }}"
            >
                Sair
            </a>

        </div>

        {% endif %}

    </div>

</nav>


<main class="container">

    {% with mensagens = get_flashed_messages(with_categories=true) %}

        {% for categoria, mensagem in mensagens %}

            <div class="flash {{ categoria }}">
                {{ mensagem }}
            </div>

        {% endfor %}

    {% endwith %}


    {{ conteudo|safe }}

</main>


<footer>

    TaskFlow • Python + Flask + SQLite

</footer>

</body>

</html>
"""


def pagina(conteudo, titulo="TaskFlow"):

    return render_template_string(
        BASE_HTML,
        conteudo=conteudo,
        titulo=titulo,
        css=CSS
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if usuario_logado():

        return redirect(
            url_for("perfis")
        )


    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        senha = request.form.get(
            "senha",
            ""
        )


        if not email or not senha:

            flash(
                "Preencha todos os campos.",
                "erro"
            )

            return redirect(
                url_for("login")
            )


        db = get_db()

        usuario = db.execute(
            """
            SELECT *

            FROM usuarios

            WHERE email = ?
            """,
            (email,)
        ).fetchone()


        if (
            usuario
            and check_password_hash(
                usuario["senha"],
                senha
            )
        ):

            session.clear()

            session["usuario_id"] = usuario["id"]

            session["usuario_nome"] = usuario["nome"]


            # Se existir apenas um perfil,
            # já entra nele.

            perfis = db.execute(
                """
                SELECT *

                FROM perfis

                WHERE usuario_id = ?

                ORDER BY id
                """,
                (usuario["id"],)
            ).fetchall()


            if len(perfis) == 1:

                session["perfil_id"] = perfis[0]["id"]

                return redirect(
                    url_for("inicio")
                )


            return redirect(
                url_for("perfis")
            )


        flash(
            "E-mail ou senha incorretos.",
            "erro"
        )


    conteudo = """
    <div class="auth-container">

        <div class="auth-card">

            <h1>🔐 Entrar</h1>

            <p class="descricao">
                Entre na sua conta do TaskFlow.
            </p>

            <form method="POST">

                <div class="form-group">

                    <label>E-mail</label>

                    <input
                        type="email"
                        name="email"
                        placeholder="seu@email.com"
                        required
                    >

                </div>


                <div class="form-group">

                    <label>Senha</label>

                    <input
                        type="password"
                        name="senha"
                        placeholder="Sua senha"
                        required
                    >

                </div>


                <button
                    class="btn btn-primary auth-button"
                    type="submit"
                >
                    Entrar
                </button>

            </form>


            <div class="auth-link">

                Ainda não possui conta?

                <a href="{{ url_for('cadastro') }}">
                    Criar conta
                </a>

            </div>

        </div>

    </div>
    """

    return pagina(
        render_template_string(
            conteudo
        ),
        "Login"
    )


# ============================================================
# CADASTRO
# ============================================================

@app.route(
    "/cadastro",
    methods=["GET", "POST"]
)
def cadastro():

    if usuario_logado():

        return redirect(
            url_for("perfis")
        )


    if request.method == "POST":

        nome = request.form.get(
            "nome",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        senha = request.form.get(
            "senha",
            ""
        )

        confirmar = request.form.get(
            "confirmar",
            ""
        )


        if not nome or not email or not senha:

            flash(
                "Preencha todos os campos.",
                "erro"
            )

            return redirect(
                url_for("cadastro")
            )


        if len(nome) < 2:

            flash(
                "O nome precisa ter pelo menos 2 caracteres.",
                "erro"
            )

            return redirect(
                url_for("cadastro")
            )


        if len(senha) < 6:

            flash(
                "A senha precisa ter pelo menos 6 caracteres.",
                "erro"
            )

            return redirect(
                url_for("cadastro")
            )


        if senha != confirmar:

            flash(
                "As senhas não são iguais.",
                "erro"
            )

            return redirect(
                url_for("cadastro")
            )


        db = get_db()


        existente = db.execute(
            """
            SELECT id

            FROM usuarios

            WHERE email = ?
            """,
            (email,)
        ).fetchone()


        if existente:

            flash(
                "Este e-mail já está cadastrado.",
                "erro"
            )

            return redirect(
                url_for("cadastro")
            )


        senha_hash = generate_password_hash(
            senha
        )


        try:

            cursor = db.execute(
                """
                INSERT INTO usuarios
                    (nome, email, senha)

                VALUES
                    (?, ?, ?)
                """,
                (
                    nome,
                    email,
                    senha_hash
                )
            )


            novo_usuario_id = cursor.lastrowid


            # Cria automaticamente o primeiro perfil.

            cursor = db.execute(
                """
                INSERT INTO perfis
                    (usuario_id, nome, avatar)

                VALUES
                    (?, ?, ?)
                """,
                (
                    novo_usuario_id,
                    nome,
                    "😀"
                )
            )


            novo_perfil_id = cursor.lastrowid


            db.commit()


        except sqlite3.IntegrityError:

            db.rollback()

            flash(
                "Não foi possível criar a conta.",
                "erro"
            )

            return redirect(
                url_for("cadastro")
            )


        session.clear()

        session["usuario_id"] = novo_usuario_id

        session["usuario_nome"] = nome

        session["perfil_id"] = novo_perfil_id


        flash(
            "Conta criada com sucesso! 🎉",
            "sucesso"
        )


        return redirect(
            url_for("inicio")
        )


    conteudo = """
    <div class="auth-container">

        <div class="auth-card">

            <h1>🚀 Criar conta</h1>

            <p class="descricao">
                Crie sua conta do TaskFlow.
            </p>


            <form method="POST">

                <div class="form-group">

                    <label>Nome</label>

                    <input
                        type="text"
                        name="nome"
                        maxlength="80"
                        placeholder="Seu nome"
                        required
                    >

                </div>


                <div class="form-group">

                    <label>E-mail</label>

                    <input
                        type="email"
                        name="email"
                        maxlength="150"
                        placeholder="seu@email.com"
                        required
                    >

                </div>


                <div class="form-group">

                    <label>Senha</label>

                    <input
                        type="password"
                        name="senha"
                        minlength="6"
                        placeholder="Mínimo 6 caracteres"
                        required
                    >

                </div>


                <div class="form-group">

                    <label>Confirmar senha</label>

                    <input
                        type="password"
                        name="confirmar"
                        minlength="6"
                        placeholder="Digite novamente"
                        required
                    >

                </div>


                <button
                    class="btn btn-primary auth-button"
                    type="submit"
                >
                    Criar minha conta
                </button>

            </form>


            <div class="auth-link">

                Já possui conta?

                <a href="{{ url_for('login') }}">
                    Entrar
                </a>

            </div>

        </div>

    </div>
    """

    return pagina(
        render_template_string(conteudo),
        "Criar conta"
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "Você saiu da conta.",
        "sucesso"
    )

    return redirect(
        url_for("login")
    )


# ============================================================
# SELEÇÃO DE PERFIS
# ============================================================

@app.route("/perfis")
@exigir_login
def perfis():

    db = get_db()

    perfis = db.execute(
        """
        SELECT

            p.*,

            (
                SELECT COUNT(*)

                FROM tarefas t

                WHERE t.perfil_id = p.id
            ) AS total_tarefas,

            (
                SELECT COUNT(*)

                FROM tarefas t

                WHERE t.perfil_id = p.id

                AND t.concluida = 1
            ) AS tarefas_concluidas

        FROM perfis p

        WHERE p.usuario_id = ?

        ORDER BY p.id
        """,
        (usuario_id(),)
    ).fetchall()


    cards = ""


    for p in perfis:

        total = p["total_tarefas"] or 0

        concluidas = (
            p["tarefas_concluidas"]
            or 0
        )


        if total > 0:

            progresso = round(
                (concluidas / total) * 100
            )

        else:

            progresso = 0


        atual = (
            "atual"
            if p["id"] == perfil_id()
            else ""
        )


        cards += f"""
        <a
            href="/selecionar-perfil/{p['id']}"
            class="perfil-card {atual}"
        >

            <div class="perfil-avatar">
                {p["avatar"]}
            </div>

            <strong>
                {p["nome"]}
            </strong>

            <span>
                📊 Progresso: {progresso}%
            </span>

        </a>
        """


    if len(perfis) < MAX_PERFIS:

        cards += """
        <a
            href="/criar-perfil"
            class="perfil-card novo-perfil"
        >

            <div class="perfil-avatar">
                +
            </div>

            <strong>
                Criar perfil
            </strong>

            <span>
                Novo perfil
            </span>

        </a>
        """


    conteudo = f"""
    <div class="perfis-header">

        <h1>👥 Quem está usando?</h1>

        <p>
            Escolha um perfil para continuar no TaskFlow.
        </p>

    </div>


    <div class="perfis-grid">

        {cards}

    </div>
    """


    return pagina(
        conteudo,
        "Escolher perfil"
    )


# ============================================================
# SELECIONAR PERFIL
# ============================================================

@app.route(
    "/selecionar-perfil/<int:id>"
)
@exigir_login
def selecionar_perfil(id):

    db = get_db()

    perfil = db.execute(
        """
        SELECT *

        FROM perfis

        WHERE id = ?

        AND usuario_id = ?
        """,
        (
            id,
            usuario_id()
        )
    ).fetchone()


    if not perfil:

        flash(
            "Perfil não encontrado.",
            "erro"
        )

        return redirect(
            url_for("perfis")
        )


    session["perfil_id"] = perfil["id"]

    session["perfil_nome"] = perfil["nome"]

    session["perfil_avatar"] = perfil["avatar"]


    return redirect(
        url_for("inicio")
    )


# ============================================================
# CRIAR PERFIL
# ============================================================

@app.route(
    "/criar-perfil",
    methods=["GET", "POST"]
)
@exigir_login
def criar_perfil():

    db = get_db()

    quantidade = db.execute(
        """
        SELECT COUNT(*) AS total

        FROM perfis

        WHERE usuario_id = ?
        """,
        (usuario_id(),)
    ).fetchone()["total"]


    if quantidade >= MAX_PERFIS:

        flash(
            "Você já possui o máximo de 5 perfis.",
            "erro"
        )

        return redirect(
            url_for("perfis")
        )


    if request.method == "POST":

        nome = request.form.get(
            "nome",
            ""
        ).strip()

        avatar = request.form.get(
            "avatar",
            "😀"
        )


        if not nome:

            flash(
                "Digite um nome para o perfil.",
                "erro"
            )

            return redirect(
                url_for("criar_perfil")
            )


        if len(nome) > 40:

            flash(
                "O nome é muito longo.",
                "erro"
            )

            return redirect(
                url_for("criar_perfil")
            )


        if avatar not in AVATARES:

            avatar = "😀"


        cursor = db.execute(
            """
            INSERT INTO perfis
                (usuario_id, nome, avatar)

            VALUES
                (?, ?, ?)
            """,
            (
                usuario_id(),
                nome,
                avatar
            )
        )


        db.commit()


        session["perfil_id"] = cursor.lastrowid

        session["perfil_nome"] = nome

        session["perfil_avatar"] = avatar


        flash(
            "Perfil criado! 🎉",
            "sucesso"
        )


        return redirect(
            url_for("inicio")
        )


    avatares_html = ""


    for avatar in AVATARES:

        avatares_html += f"""
        <button
            type="button"
            class="avatar-option"
            onclick="selecionarAvatar(this, '{avatar}')"
        >
            {avatar}
        </button>
        """


    conteudo = f"""
    <a
        href="/perfis"
        class="btn-voltar"
    >
        ← Voltar para perfis
    </a>


    <div class="card">

        <div class="page-title">

            <h1>➕ Criar perfil</h1>

            <p>
                Crie um novo perfil para organizar
                suas próprias tarefas.
            </p>

        </div>


        <form method="POST">

            <div class="form-group">

                <label>Nome do perfil</label>

                <input
                    type="text"
                    name="nome"
                    maxlength="40"
                    placeholder="Ex: João"
                    required
                >

            </div>


            <input
                type="hidden"
                name="avatar"
                id="avatar"
                value="😀"
            >


            <div class="avatar-section">

                <h2>🎨 Escolha seu avatar</h2>

                <p>
                    Escolha um emoji para representar o perfil.
                </p>

                <div class="avatar-grid">

                    {avatares_html}

                </div>

            </div>


            <button
                type="submit"
                class="btn btn-primary"
                style="margin-top:25px"
            >
                Criar perfil
            </button>

        </form>

    </div>


    <script>

    function selecionarAvatar(botao, avatar) {{

        document.getElementById("avatar").value = avatar;

        document
            .querySelectorAll(".avatar-option")
            .forEach(function(elemento) {{
                elemento.classList.remove("selecionado");
            }});

        botao.classList.add("selecionado");
    }}

    </script>
    """


    return pagina(
        conteudo,
        "Criar perfil"
    )


# ============================================================
# PERFIL
# ============================================================

@app.route(
    "/perfil",
    methods=["GET", "POST"]
)
@exigir_perfil
def perfil():

    db = get_db()


    if request.method == "POST":

        nome = request.form.get(
            "nome",
            ""
        ).strip()

        avatar = request.form.get(
            "avatar",
            "😀"
        )


        if not nome:

            flash(
                "O nome não pode ficar vazio.",
                "erro"
            )

            return redirect(
                url_for("perfil")
            )


        if avatar not in AVATARES:

            avatar = "😀"


        db.execute(
            """
            UPDATE perfis

            SET nome = ?,
                avatar = ?

            WHERE id = ?

            AND usuario_id = ?
            """,
            (
                nome,
                avatar,
                perfil_id(),
                usuario_id()
            )
        )


        db.commit()


        session["perfil_nome"] = nome

        session["perfil_avatar"] = avatar


        flash(
            "Perfil atualizado! ✅",
            "sucesso"
        )


        return redirect(
            url_for("perfil")
        )


    perfil_atual = db.execute(
        """
        SELECT *

        FROM perfis

        WHERE id = ?

        AND usuario_id = ?
        """,
        (
            perfil_id(),
            usuario_id()
        )
    ).fetchone()


    # Estatísticas do perfil.

    estatisticas = db.execute(
        """
        SELECT

            COUNT(*) AS total,

            SUM(
                CASE
                    WHEN concluida = 1
                    THEN 1
                    ELSE 0
                END
            ) AS concluidas

        FROM tarefas

        WHERE perfil_id = ?
        """,
        (perfil_id(),)
    ).fetchone()


    total = estatisticas["total"] or 0

    concluidas = (
        estatisticas["concluidas"]
        or 0
    )


    if total:

        progresso = round(
            concluidas / total * 100
        )

    else:

        progresso = 0


    # --------------------------------------------------------
    # AVATARES
    # --------------------------------------------------------

    avatares_html = ""


    for avatar in AVATARES:

        selecionado = (
            "selecionado"
            if avatar == perfil_atual["avatar"]
            else ""
        )


        avatares_html += f"""
        <button
            type="button"
            class="avatar-option {selecionado}"
            onclick="selecionarAvatar(this, '{avatar}')"
        >
            {avatar}
        </button>
        """


    # --------------------------------------------------------
    # OUTROS PERFIS
    # --------------------------------------------------------

    perfis = db.execute(
        """
        SELECT *

        FROM perfis

        WHERE usuario_id = ?

        ORDER BY id
        """,
        (usuario_id(),)
    ).fetchall()


    outros_perfis = ""


    for p in perfis:

        classe = (
            "atual"
            if p["id"] == perfil_id()
            else ""
        )


        outros_perfis += f"""
        <a
            href="/selecionar-perfil/{p['id']}"
            class="perfil-card {classe}"
        >

            <div class="perfil-avatar">
                {p["avatar"]}
            </div>

            <strong>
                {p["nome"]}
            </strong>

            <span>
                {"Perfil atual" if p["id"] == perfil_id() else "Trocar para este perfil"}
            </span>

        </a>
        """


    if len(perfis) < MAX_PERFIS:

        outros_perfis += """
        <a
            href="/criar-perfil"
            class="perfil-card novo-perfil"
        >

            <div class="perfil-avatar">
                +
            </div>

            <strong>
                Criar perfil
            </strong>

            <span>
                Novo perfil
            </span>

        </a>
        """


    # --------------------------------------------------------
    # CONTEÚDO
    # --------------------------------------------------------

    conteudo = f"""
    <a
        href="/"
        class="btn-voltar"
    >
        ← Voltar para tarefas
    </a>


    <div class="page-title">

        <h1>
            👤 Meu perfil
        </h1>

        <p>
            Personalize seu perfil do TaskFlow.
        </p>

    </div>


    <div class="card">

        <div class="perfil-topo">

            <div class="perfil-topo-avatar">
                {perfil_atual["avatar"]}
            </div>

            <div>

                <h1>
                    {perfil_atual["nome"]}
                </h1>

                <p>
                    {session.get("usuario_nome", "")}
                </p>

                <div class="progresso-mini">
                    📊 Progresso: {progresso}%
                </div>

            </div>

        </div>


        <form method="POST">

            <div class="form-group">

                <label>
                    Nome do perfil
                </label>

                <input
                    type="text"
                    name="nome"
                    maxlength="40"
                    value="{perfil_atual["nome"]}"
                    required
                >

            </div>


            <input
                type="hidden"
                name="avatar"
                id="avatar"
                value="{perfil_atual["avatar"]}"
            >


            <div class="avatar-section">

                <h2>
                    🎨 Escolha seu avatar
                </h2>

                <p>
                    Escolha um emoji para representar seu perfil.
                </p>


                <div class="avatar-grid">

                    {avatares_html}

                </div>

            </div>


            <button
                type="submit"
                class="btn btn-primary"
                style="margin-top:25px"
            >
                💾 Salvar alterações
            </button>

        </form>

    </div>


    <div class="card escolher-perfil">

        <h2>
            👥 Escolher perfil
        </h2>

        <p>
            Escolha quem está usando o TaskFlow.
        </p>


        <div class="perfis-grid">

            {outros_perfis}

        </div>

    </div>


    <div class="card" style="margin-top:30px">

        <h2>
            🗑️ Gerenciar perfil
        </h2>

        <p
            style="
                color:#94a3b8;
                margin:8px 0 18px;
            "
        >
            Excluir este perfil também excluirá
            as tarefas pertencentes a ele.
        </p>


        <form
            method="POST"
            action="/excluir-perfil"
            onsubmit="return confirm('Tem certeza que deseja excluir este perfil?')"
        >

            <button
                type="submit"
                class="btn btn-danger"
            >
                🗑️ Excluir perfil
            </button>

        </form>

    </div>


    <script>

    function selecionarAvatar(botao, avatar) {{

        document.getElementById("avatar").value = avatar;

        document
            .querySelectorAll(".avatar-option")
            .forEach(function(elemento) {{
                elemento.classList.remove("selecionado");
            }});

        botao.classList.add("selecionado");
    }}

    </script>
    """


    return pagina(
        conteudo,
        "Meu perfil"
    )


# ============================================================
# EXCLUIR PERFIL
# ============================================================

@app.route(
    "/excluir-perfil",
    methods=["POST"]
)
@exigir_perfil
def excluir_perfil():

    db = get_db()


    quantidade = db.execute(
        """
        SELECT COUNT(*) AS total

        FROM perfis

        WHERE usuario_id = ?
        """,
        (usuario_id(),)
    ).fetchone()["total"]


    if quantidade <= 1:

        flash(
            "Você precisa manter pelo menos um perfil.",
            "erro"
        )

        return redirect(
            url_for("perfil")
        )


    db.execute(
        """
        DELETE FROM perfis

        WHERE id = ?

        AND usuario_id = ?
        """,
        (
            perfil_id(),
            usuario_id()
        )
    )


    db.commit()


    session.pop(
        "perfil_id",
        None
    )

    session.pop(
        "perfil_nome",
        None
    )

    session.pop(
        "perfil_avatar",
        None
    )


    flash(
        "Perfil excluído.",
        "sucesso"
    )


    return redirect(
        url_for("perfis")
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/")
@exigir_perfil
def inicio():

    db = get_db()


    perfil = db.execute(
        """
        SELECT *

        FROM perfis

        WHERE id = ?

        AND usuario_id = ?
        """,
        (
            perfil_id(),
            usuario_id()
        )
    ).fetchone()


    filtro = request.args.get(
        "filtro",
        "todas"
    )


    if filtro == "pendentes":

        condicao = """
            AND concluida = 0
        """

    elif filtro == "concluidas":

        condicao = """
            AND concluida = 1
        """

    else:

        condicao = ""


    tarefas = db.execute(
        f"""
        SELECT *

        FROM tarefas

        WHERE perfil_id = ?

        {condicao}

        ORDER BY

            concluida ASC,

            CASE prioridade

                WHEN 'alta' THEN 1

                WHEN 'media' THEN 2

                ELSE 3

            END,

            CASE

                WHEN data_vencimento IS NULL
                THEN 1

                ELSE 0

            END,

            data_vencimento ASC,

            id DESC
        """,
        (perfil_id(),)
    ).fetchall()


    # --------------------------------------------------------
    # ESTATÍSTICAS
    # --------------------------------------------------------

    estatisticas = db.execute(
        """
        SELECT

            COUNT(*) AS total,

            SUM(
                CASE
                    WHEN concluida = 0
                    THEN 1
                    ELSE 0
                END
            ) AS pendentes,

            SUM(
                CASE
                    WHEN concluida = 1
                    THEN 1
                    ELSE 0
                END
            ) AS concluidas

        FROM tarefas

        WHERE perfil_id = ?
        """,
        (perfil_id(),)
    ).fetchone()


    total = estatisticas["total"] or 0

    pendentes = (
        estatisticas["pendentes"]
        or 0
    )

    concluidas = (
        estatisticas["concluidas"]
        or 0
    )


    if total:

        progresso = round(
            concluidas / total * 100
        )

    else:

        progresso = 0


    # --------------------------------------------------------
    # CARDS DE TAREFAS
    # --------------------------------------------------------

    cards = ""


    for tarefa in tarefas:

        prioridade = tarefa["prioridade"] or "media"


        if prioridade not in PRIORIDADES:

            prioridade = "media"


        info_prioridade = PRIORIDADES[
            prioridade
        ]


        data = tarefa["data_vencimento"]


        if data:

            partes = data.split("-")

            if len(partes) == 3:

                data_formatada = (
                    f"{partes[2]}/"
                    f"{partes[1]}/"
                    f"{partes[0]}"
                )

            else:

                data_formatada = data

        else:

            data_formatada = "Sem prazo"


        atrasada = False


        if data and not tarefa["concluida"]:

            from datetime import date

            try:

                vencimento = date.fromisoformat(
                    data
                )

                atrasada = (
                    vencimento < date.today()
                )

            except ValueError:

                atrasada = False


        badge_data = ""


        if data:

            if atrasada:

                badge_data = f"""
                <span class="badge atrasada">
                    ⚠️ Vencida: {data_formatada}
                </span>
                """

            else:

                badge_data = f"""
                <span class="badge">
                    📅 {data_formatada}
                </span>
                """

        else:

            badge_data = """
            <span class="badge">
                📅 Sem prazo
            </span>
            """


        classe = (
            "concluida"
            if tarefa["concluida"]
            else prioridade
        )


        botao_concluir = (
            "↩ Reabrir"
            if tarefa["concluida"]
            else "✓ Concluir"
        )


        cards += f"""
        <div class="tarefa {classe}">

            <div>

                <h3>
                    {tarefa["titulo"]}
                </h3>


                <div class="tarefa-meta">

                    <span
                        class="badge"
                        style="
                            border-left:
                            3px solid
                            {info_prioridade["cor"]};
                        "
                    >
                        {info_prioridade["emoji"]}
                        Prioridade:
                        {info_prioridade["nome"]}
                    </span>


                    {badge_data}


                    <span class="badge">

                        {
                            "✅ Concluída"
                            if tarefa["concluida"]
                            else "⏳ Pendente"
                        }

                    </span>

                </div>

            </div>


            <div class="acoes">

                <form
                    method="POST"
                    action="/concluir/{tarefa['id']}"
                >

                    <button
                        class="btn btn-success"
                        type="submit"
                    >
                        {botao_concluir}
                    </button>

                </form>


                <a
                    class="btn btn-warning"
                    href="/editar-tarefa/{tarefa['id']}"
                >
                    ✏️ Editar
                </a>


                <form
                    method="POST"
                    action="/excluir/{tarefa['id']}"
                    onsubmit="return confirm('Excluir esta tarefa?')"
                >

                    <button
                        class="btn btn-danger"
                        type="submit"
                    >
                        🗑️
                    </button>

                </form>

            </div>

        </div>
        """


    if not cards:

        cards = """
        <div class="vazio">

            <h3>
                📭 Nenhuma tarefa encontrada.
            </h3>

            <p style="margin-top:8px">
                Crie uma tarefa acima para começar.
            </p>

        </div>
        """


    conteudo = f"""
    <div class="dashboard-header">

        <div>

            <h1>
                Minhas tarefas
            </h1>

            <p>
                Organize seu dia e acompanhe seu progresso.
            </p>

        </div>


        <a
            href="/perfil"
            class="perfil-atual"
        >

            <span class="avatar">
                {perfil["avatar"]}
            </span>

            <span>
                {perfil["nome"]}
            </span>

        </a>

    </div>


    <div class="progresso-card">

        <div class="progresso-header">

            <span>
                📊 Progresso do perfil
            </span>

            <span>
                {progresso}%
            </span>

        </div>


        <div class="barra">

            <div
                class="barra-progresso"
                style="width:{progresso}%"
            ></div>

        </div>

    </div>


    <div class="estatisticas">

        <div class="stat">

            <span class="numero">
                {total}
            </span>

            <span class="label">
                📋 Total
            </span>

        </div>


        <div class="stat">

            <span class="numero">
                {pendentes}
            </span>

            <span class="label">
                ⏳ Pendentes
            </span>

        </div>


        <div class="stat">

            <span class="numero">
                {concluidas}
            </span>

            <span class="label">
                ✅ Concluídas
            </span>

        </div>


        <div class="stat">

            <span class="numero">
                {progresso}%
            </span>

            <span class="label">
                📈 Progresso
            </span>

        </div>

    </div>


    <div class="nova-tarefa">

        <form
            method="POST"
            action="/adicionar"
        >

            <div class="nova-grid">

                <input
                    type="text"
                    name="titulo"
                    placeholder="O que você precisa fazer?"
                    maxlength="200"
                    required
                >


                <input
                    type="date"
                    name="data_vencimento"
                >


                <select name="prioridade">

                    <option value="baixa">
                        🟢 Baixa
                    </option>

                    <option
                        value="media"
                        selected
                    >
                        🟡 Média
                    </option>

                    <option value="alta">
                        🔴 Alta
                    </option>

                </select>


                <button
                    type="submit"
                    class="btn btn-success"
                >
                    + Adicionar
                </button>

            </div>

        </form>

    </div>


    <div class="filtros">

        <a
            class="filtro {"ativo" if filtro == "todas" else ""}"
            href="/?filtro=todas"
        >
            📋 Todas
        </a>


        <a
            class="filtro {"ativo" if filtro == "pendentes" else ""}"
            href="/?filtro=pendentes"
        >
            ⏳ Pendentes
        </a>


        <a
            class="filtro {"ativo" if filtro == "concluidas" else ""}"
            href="/?filtro=concluidas"
        >
            ✅ Concluídas
        </a>

    </div>


    <section>

        {cards}

    </section>
    """


    return pagina(
        conteudo,
        "Minhas tarefas"
    )


# ============================================================
# ADICIONAR TAREFA
# ============================================================

@app.route(
    "/adicionar",
    methods=["POST"]
)
@exigir_perfil
def adicionar():

    titulo = request.form.get(
        "titulo",
        ""
    ).strip()

    data_vencimento = request.form.get(
        "data_vencimento",
        ""
    ).strip()

    prioridade = request.form.get(
        "prioridade",
        "media"
    )


    if not titulo:

        flash(
            "Digite uma tarefa.",
            "erro"
        )

        return redirect(
            url_for("inicio")
        )


    if len(titulo) > 200:

        flash(
            "A tarefa é muito longa.",
            "erro"
        )

        return redirect(
            url_for("inicio")
        )


    if prioridade not in PRIORIDADES:

        prioridade = "media"


    db = get_db()


    db.execute(
        """
        INSERT INTO tarefas
            (
                usuario_id,
                perfil_id,
                titulo,
                data_vencimento,
                prioridade
            )

        VALUES
            (?, ?, ?, ?, ?)
        """,
        (
            usuario_id(),
            perfil_id(),
            titulo,
            data_vencimento or None,
            prioridade
        )
    )


    db.commit()


    flash(
        "Tarefa adicionada! 🎉",
        "sucesso"
    )


    return redirect(
        url_for("inicio")
    )


# ============================================================
# EDITAR TAREFA
# ============================================================

@app.route(
    "/editar-tarefa/<int:id>",
    methods=["GET", "POST"]
)
@exigir_perfil
def editar_tarefa(id):

    db = get_db()


    tarefa = db.execute(
        """
        SELECT *

        FROM tarefas

        WHERE id = ?

        AND perfil_id = ?

        AND usuario_id = ?
        """,
        (
            id,
            perfil_id(),
            usuario_id()
        )
    ).fetchone()


    if not tarefa:

        flash(
            "Tarefa não encontrada.",
            "erro"
        )

        return redirect(
            url_for("inicio")
        )


    if request.method == "POST":

        titulo = request.form.get(
            "titulo",
            ""
        ).strip()

        data_vencimento = request.form.get(
            "data_vencimento",
            ""
        ).strip()

        prioridade = request.form.get(
            "prioridade",
            "media"
        )


        if not titulo:

            flash(
                "Digite um título.",
                "erro"
            )

            return redirect(
                url_for(
                    "editar_tarefa",
                    id=id
                )
            )


        if prioridade not in PRIORIDADES:

            prioridade = "media"


        db.execute(
            """
            UPDATE tarefas

            SET titulo = ?,

                data_vencimento = ?,

                prioridade = ?,

                atualizado_em =
                    CURRENT_TIMESTAMP

            WHERE id = ?

            AND perfil_id = ?

            AND usuario_id = ?
            """,
            (
                titulo,
                data_vencimento or None,
                prioridade,
                id,
                perfil_id(),
                usuario_id()
            )
        )


        db.commit()


        flash(
            "Tarefa atualizada! ✏️",
            "sucesso"
        )


        return redirect(
            url_for("inicio")
        )


    opcoes_prioridade = ""


    for chave, info in PRIORIDADES.items():

        selecionado = (
            "selected"
            if tarefa["prioridade"] == chave
            else ""
        )


        opcoes_prioridade += f"""
        <option
            value="{chave}"
            {selecionado}
        >
            {info["emoji"]}
            {info["nome"]}
        </option>
        """


    conteudo = f"""
    <a
        href="/"
        class="btn-voltar"
    >
        ← Voltar para tarefas
    </a>


    <div class="card">

        <div class="page-title">

            <h1>✏️ Editar tarefa</h1>

            <p>
                Altere as informações da sua tarefa.
            </p>

        </div>


        <form method="POST">

            <div class="form-group">

                <label>
                    Tarefa
                </label>

                <input
                    type="text"
                    name="titulo"
                    value="{tarefa["titulo"]}"
                    maxlength="200"
                    required
                >

            </div>


            <div class="form-group">

                <label>
                    📅 Data de vencimento
                </label>

                <input
                    type="date"
                    name="data_vencimento"
                    value="{tarefa["data_vencimento"] or ""}"
                >

            </div>


            <div class="form-group">

                <label>
                    🚦 Prioridade
                </label>

                <select name="prioridade">

                    {opcoes_prioridade}

                </select>

            </div>


            <button
                type="submit"
                class="btn btn-primary"
            >
                💾 Salvar alterações
            </button>


            <a
                href="/"
                class="btn btn-secondary"
            >
                Cancelar
            </a>

        </form>

    </div>
    """


    return pagina(
        conteudo,
        "Editar tarefa"
    )


# ============================================================
# CONCLUIR / REABRIR
# ============================================================

@app.route(
    "/concluir/<int:id>",
    methods=["POST"]
)
@exigir_perfil
def concluir(id):

    db = get_db()


    tarefa = db.execute(
        """
        SELECT concluida

        FROM tarefas

        WHERE id = ?

        AND perfil_id = ?

        AND usuario_id = ?
        """,
        (
            id,
            perfil_id(),
            usuario_id()
        )
    ).fetchone()


    if not tarefa:

        flash(
            "Tarefa não encontrada.",
            "erro"
        )

        return redirect(
            url_for("inicio")
        )


    novo_status = (
        0
        if tarefa["concluida"]
        else 1
    )


    db.execute(
        """
        UPDATE tarefas

        SET concluida = ?,

            atualizado_em =
                CURRENT_TIMESTAMP

        WHERE id = ?

        AND perfil_id = ?

        AND usuario_id = ?
        """,
        (
            novo_status,
            id,
            perfil_id(),
            usuario_id()
        )
    )


    db.commit()


    return redirect(
        url_for("inicio")
    )


# ============================================================
# EXCLUIR TAREFA
# ============================================================

@app.route(
    "/excluir/<int:id>",
    methods=["POST"]
)
@exigir_perfil
def excluir(id):

    db = get_db()


    db.execute(
        """
        DELETE FROM tarefas

        WHERE id = ?

        AND perfil_id = ?

        AND usuario_id = ?
        """,
        (
            id,
            perfil_id(),
            usuario_id()
        )
    )


    db.commit()


    flash(
        "Tarefa excluída. 🗑️",
        "sucesso"
    )


    return redirect(
        url_for("inicio")
    )


# ============================================================
# INICIALIZAÇÃO
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 55)
    print("        TASKFLOW - PYTHON + FLASK")
    print("=" * 55)
    print()
    print("Banco:", BANCO)
    print()
    print("Inicializando banco de dados...")

    criar_banco()

    print("Banco pronto!")
    print()
    print("Acesse:")
    print("http://127.0.0.1:5000")
    print()

    # use_reloader=False evita que o modo de desenvolvimento
    # abra outro processo do Flask e ajuda a evitar conflitos
    # desnecessários com o SQLite.

    app.run(
        debug=True,
        use_reloader=False
    )