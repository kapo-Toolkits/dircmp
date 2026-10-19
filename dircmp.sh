#!/usr/bin/env bash
# dircmp — ერთი ფაილით გაშვება / one-file launcher.
#
# პირველ გაშვებაზე ამზადებს Python-ის გარემოს (.venv). თუ სისტემას რამე აკლია
# (მაგ. libxcb-cursor0, რომლის გარეშეც Qt-ის ფანჯარა არ იხსნება), ჯერ გეკითხებათ
# და მხოლოდ თანხმობის შემდეგ აყენებს. შემდეგ ხსნის პროგრამას.
#
#   ./dircmp.sh [FOLDER ...]       GUI (საქაღალდეები სიაში წინასწარ ჩაიწერება)
#   ./dircmp.sh --cli A B C ...    ბრძანების ხაზის რეჟიმი
#
# ტერმინალიდან გაშვებისას კითხვები ტერმინალში ჩნდება (sudo), ორმაგი დაწკაპუნებისას —
# დიალოგებად (zenity) და პაროლის ფანჯრით (pkexec).
set -uo pipefail

DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
VENV="$DIR/.venv"
ICON="$DIR/dircmp/gui/resources/dircmp.svg"
LOG="${XDG_CACHE_HOME:-$HOME/.cache}/dircmp-setup.log"
TITLE="dircmp"
[[ -t 0 && -t 1 ]] && TTY=1 || TTY=0

has() { command -v "$1" >/dev/null 2>&1; }

info() {
    if ((TTY)); then echo "$*"
    elif has notify-send; then notify-send -i "$ICON" "$TITLE" "$*"
    fi
}

fail() {
    if ((TTY)); then echo "შეცდომა: $*" >&2
    elif has zenity; then zenity --error --title="$TITLE" --width=460 --text="$*"
    fi
    exit 1
}

ask() {  # ask <question> -> 0 on yes
    if ((TTY)); then
        local a
        read -r -p "$* [y/n] " a
        [[ "$a" =~ ^([yY]|[yY]es|დ|დიახ)$ ]]
    elif has zenity; then
        zenity --question --title="$TITLE" --width=460 --ok-label="დიახ" --cancel-label="არა" --text="$*"
    else
        return 1
    fi
}

as_root() {  # sudo in a terminal, graphical password prompt otherwise
    if ((TTY)); then sudo "$@"
    elif has pkexec; then pkexec "$@"
    else fail "ადმინისტრატორის უფლებით გაშვება ვერ ხერხდება. გაუშვით ტერმინალიდან: $DIR/dircmp.sh"
    fi
}

install_pkg() {  # install_pkg <apt package> <dnf package> <why it is needed>
    local cmd
    if has apt-get; then cmd=(apt-get install -y "$1")
    elif has dnf; then cmd=(dnf install -y "$2")
    else fail "$3"$'\n\n'"დააყენეთ ხელით: $1"
    fi
    ask "$3"$'\n\n'"დავაყენო ახლა? (საჭიროა ადმინისტრატორის პაროლი)"$'\n'"${cmd[*]}" \
        || fail "$1 არ დაყენდა, ამიტომ dircmp ვერ ჩაირთვება."
    as_root "${cmd[@]}" || fail "ინსტალაცია ვერ შესრულდა: ${cmd[*]}"
}

run_with_progress() {  # run_with_progress <message> <command...>; output goes to $LOG
    local msg=$1; shift
    mkdir -p "$(dirname "$LOG")"
    if ((TTY)); then
        echo "$msg"
        "$@" 2>&1 | tee -a "$LOG"
        return "${PIPESTATUS[0]}"
    fi
    "$@" >>"$LOG" 2>&1 &
    local pid=$!
    if has zenity; then
        while kill -0 "$pid" 2>/dev/null; do echo "#$msg"; sleep 1; done \
            | zenity --progress --pulsate --auto-close --no-cancel --title="$TITLE" --width=460 --text="$msg"
    fi
    wait "$pid"
}

# --- 1. Python environment --------------------------------------------------

first_run=0
if [[ ! -x "$VENV/bin/dircmp-gui" ]]; then
    first_run=1
    has python3 || install_pkg python3 python3 "dircmp-ს სჭირდება Python 3.12 ან უფრო ახალი."
    python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' \
        || fail "საჭიროა Python 3.12 ან უფრო ახალი (ახლა: $(python3 --version 2>&1))."
    python3 -c 'import ensurepip' 2>/dev/null \
        || install_pkg python3-venv python3 "Python-ის გარემოს შესაქმნელად საჭიროა პაკეტი python3-venv."

    run_with_progress "Python-ის გარემოს შექმნა…" python3 -m venv "$VENV" \
        || fail "გარემო ვერ შეიქმნა. დეტალები: $LOG"
    run_with_progress "dircmp-ისა და PySide6-ის დაყენება (პირველად რამდენიმე წუთი)…" \
        "$VENV/bin/python" -m pip install --disable-pip-version-check -e "$DIR[gui]" \
        || { rm -rf "$VENV"; fail "დამოკიდებულებები ვერ დაყენდა (ინტერნეტი?). დეტალები: $LOG"; }
fi

if [[ "${1:-}" == "--cli" ]]; then
    shift
    exec "$VENV/bin/dircmp" "$@"
fi

# --- 2. System library for Qt on X11 ---------------------------------------

# Output is captured first: `ldconfig -p | grep -q` can fail under pipefail (SIGPIPE).
has_lib() {  # has_lib <soname>: ldconfig cache first, then a plain file lookup
    local ldconfig_bin cache d
    ldconfig_bin=$(command -v ldconfig || echo /sbin/ldconfig)
    cache=$("$ldconfig_bin" -p 2>/dev/null) || cache=""
    [[ "$cache" == *"$1"* ]] && return 0
    for d in /usr/lib /usr/lib64 /lib /lib64 /usr/lib/*-linux-gnu /lib/*-linux-gnu; do
        [[ -e "$d/$1" ]] && return 0
    done
    return 1
}

NEED_XCB=0
[[ "$(uname -s)" == "Linux" && "${XDG_SESSION_TYPE:-x11}" != "wayland" ]] && NEED_XCB=1

if ((NEED_XCB)) && ! has_lib libxcb-cursor.so.0; then
    install_pkg libxcb-cursor0 xcb-util-cursor \
        "Qt-ის ფანჯრის გასახსნელად სისტემას აკლია ბიბლიოთეკა libxcb-cursor0."
fi

# --- 3. Menu entry and desktop shortcut (asked once) ------------------------

if ((first_run)) && [[ "$(uname -s)" == "Linux" ]] \
        && [[ ! -e "${XDG_DATA_HOME:-$HOME/.local/share}/applications/io.github.kapo_toolkits.dircmp.desktop" ]]; then
    if ask "შევქმნა dircmp-ის იარლიყი მენიუში და სამუშაო მაგიდაზე?"; then
        bash "$DIR/packaging/linux/install-launcher.sh" --exec "$DIR/dircmp.sh" >>"$LOG" 2>&1 \
            && info "იარლიყი შეიქმნა."
    fi
fi

# --- 4. Run; if Qt still reports the missing library, offer the install and retry once ---

ERR=$(mktemp)
trap 'rm -f "$ERR"' EXIT
"$VENV/bin/dircmp-gui" "$@" 2> >(tee "$ERR" >&2)
rc=$?
if ((rc != 0 && NEED_XCB)) && grep -q 'xcb-cursor' "$ERR" 2>/dev/null; then
    install_pkg libxcb-cursor0 xcb-util-cursor \
        "Qt-ს ფანჯრის გასახსნელად სჭირდება ბიბლიოთეკა libxcb-cursor0."
    exec "$VENV/bin/dircmp-gui" "$@"
fi
exit "$rc"
