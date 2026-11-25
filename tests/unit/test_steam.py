from htpc import steam

LOCALCONFIG = '''"UserLocalConfigStore"
{
	"Software"
	{
		"Valve"
		{
			"Steam"
			{
				"apps"
				{
					"620"
					{
						"LastPlayed"		"1700000300"
						"Playtime"		"125"
					}
					"440"
					{
						"LastPlayed"		"1700000100"
						"Playtime"		"30"
					}
					"1493710"
					{
						"LastPlayed"		"1700000900"
					}
					"999"
					{
						"LastPlayed"		"1700000500"
					}
				}
			}
		}
	}
}
'''


def manifest(appid, name):
    return f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n}}\n'


def make_steam(home, extra_library):
    root = home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
    (root / "steamapps").mkdir(parents=True)
    (root / "userdata/123/config").mkdir(parents=True)
    (root / "userdata/123/config/localconfig.vdf").write_text(LOCALCONFIG)
    (root / "steamapps/appmanifest_620.acf").write_text(manifest(620, "Portal 2"))
    (root / "steamapps/appmanifest_1493710.acf").write_text(manifest(1493710, "Proton Experimental"))
    lib = extra_library / "steamapps"
    lib.mkdir(parents=True)
    (lib / "appmanifest_440.acf").write_text(manifest(440, 'Team \\"Fortress\\" 2'))
    (root / "steamapps/libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{root}"\n\t}}\n'
        f'\t"1"\n\t{{\n\t\t"path"\t\t"{extra_library}"\n\t}}\n}}\n')
    cache = root / "appcache/librarycache"
    (cache / "620/abc123").mkdir(parents=True)
    (cache / "620/abc123/library_600x900.jpg").write_bytes(b"jpg")
    (cache / "620/library_hero.jpg").write_bytes(b"jpg")
    (cache / "440_header.jpg").write_bytes(b"jpg")
    return root


def test_vdf_nested_and_escaped():
    data = steam.parse_vdf('// comment\n"a" { "b" "1" "c" { "d" "x \\"y\\"" } }')
    assert data == {"a": {"b": "1", "c": {"d": 'x "y"'}}}


def test_recent_games_installed_only_newest_first_with_art(tmp_path):
    root = make_steam(tmp_path / "home", tmp_path / "pool")
    games = steam.recent_games(tmp_path / "home")
    # 1493710 is Proton (not a game); 999 was played but is not installed
    assert [g["title"] for g in games] == ["Portal 2", 'Team "Fortress" 2']
    portal, tf2 = games
    assert portal["appid"] == "620" and portal["minutes"] == 125 and portal["last_played"] == 1700000300
    assert portal["poster"].endswith("620/abc123/library_600x900.jpg")
    assert portal["backdrop"] == str(root / "appcache/librarycache/620/library_hero.jpg")
    assert tf2["poster"].endswith("440_header.jpg") and tf2["backdrop"].endswith("440_header.jpg")


def test_no_steam(tmp_path):
    assert steam.recent_games(tmp_path) == [] and not steam.available(tmp_path)


def test_run_command_uses_the_same_steam():
    flatpak = {"launch": ["flatpak", "run", "com.valvesoftware.Steam", "-gamepadui"]}
    assert steam.run_command(flatpak, "620") == ["flatpak", "run", "com.valvesoftware.Steam", "steam://rungameid/620"]
    assert steam.run_command({"launch": ["steam", "-gamepadui"]}, "620") == ["steam", "steam://rungameid/620"]
    assert steam.run_command(None, "620") == ["steam", "steam://rungameid/620"]
