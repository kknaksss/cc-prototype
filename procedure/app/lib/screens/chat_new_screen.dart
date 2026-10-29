// 새 대화 · 참여자 추가(SPEC-007 §10.3 · §10.9 · DS:S3a ~ S3c · S10d) — 사람 고르기 한 화면.
// 새 대화: 1명 = [대화 시작](1:1 · 같은 상대면 기존 방) · 2명 이상 = [만들기] + 그룹 이름(선택) · 나 포함 최대 20명.
// 참여자 추가: 이미 참여 중 = 흐리게 + 「이미 참여 중」 · 못 고름 · 지금 멤버 + 고른 사람 ≤ 20. 성공하면 그 방(Room)을 돌려준다
import 'package:flutter/material.dart';

import '../api/api.dart';
import '../app_state.dart';
import '../chat/chat_model.dart';
import '../chat/chat_search.dart';
import '../chat/chat_ui.dart';
import '../theme/tokens.dart';
import '../widgets/header.dart';
import '../widgets/resv_ui.dart' show MiniChip, StatusChip;
import '../widgets/ui.dart';

const maxRoomMembers = 20;

class ChatPeopleScreen extends StatefulWidget {
  final Room? addTo; // null = 새 대화
  const ChatPeopleScreen({super.key, this.addTo});

  @override
  State<ChatPeopleScreen> createState() => _ChatPeopleScreenState();
}

class _ChatPeopleScreenState extends State<ChatPeopleScreen> {
  late final AppState _app = AppScope.read(context);
  final _search = TextEditingController();
  final _title = TextEditingController();
  List<Person>? _people;
  final List<Person> _picked = [];
  bool _busy = false;
  String? _error;

  bool get _add => widget.addTo != null;
  Set<int> get _members => {for (final m in widget.addTo?.members ?? const <Member>[]) m.id};
  // 더 고를 수 있는 수 — 새 대화 = 나 빼고 19 · 추가 = 20 − 지금 멤버
  int get _cap => _add ? maxRoomMembers - widget.addTo!.memberCount : maxRoomMembers - 1;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _search.dispose();
    _title.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final l = await _app.api.chatPeople();
      if (mounted) setState(() => _people = l);
    } on ApiError catch (e) {
      if (e.status == 401) return _app.logout(message: '로그인이 풀렸어요 — 다시 로그인하세요');
      if (mounted) setState(() => _error = e.message);
    }
  }

  void _toggle(Person p) => setState(() {
        if (_picked.any((x) => x.id == p.id)) {
          _picked.removeWhere((x) => x.id == p.id);
        } else if (_picked.length < _cap) {
          _picked.add(p);
        }
      });

  String get _action => _add ? '추가' : (_picked.length <= 1 ? '대화 시작' : '만들기');

  String get _guide {
    final n = _picked.length;
    if (_add) return '$n명 선택 · 지금 ${widget.addTo!.memberCount}명 · 최대 $maxRoomMembers명';
    if (n == 1) return '1명 선택 · 1:1 대화';
    return '$n명 선택 · 나 포함 ${n + 1}명 · 최대 $maxRoomMembers명';
  }

  Future<void> _submit() async {
    if (_picked.isEmpty || _busy) return;
    setState(() => _busy = true);
    Room? r;
    final ids = [for (final p in _picked) p.id];
    await _app.run(() async {
      r = _add
          ? await _app.chat.addMembers(widget.addTo!.id, ids)
          : ids.length == 1
              ? await _app.chat.openDirect(ids.first)
              : await _app.chat.createGroup(ids, title: _title.text);
    });
    if (!mounted) return;
    setState(() => _busy = false);
    if (r != null) Navigator.of(context).pop(r);
  }

  @override
  Widget build(BuildContext context) {
    final q = _search.text.trim();
    final people = _people;
    final shown = people == null ? const <Person>[] : people.where((p) => nameMatches(p.name, q)).toList(); // 초성 가능(OQ-961 — 전달 시트와 같은 함수)
    final members = _members;
    return Material(
      color: Ms.gray100,
      child: SafeArea(
        bottom: false,
        child: Column(children: [
          DetailHeader(
            back: '취소',
            title: _add ? '참여자 추가' : '새 대화',
            trailing: MsButton(_action, size: BtnSize.sm, onPressed: _picked.isEmpty || _busy ? null : _submit),
          ),
          Container(
            color: Ms.white,
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              MsInput(controller: _search, hint: '이름 검색', icon: Icons.search_rounded, onChanged: (_) => setState(() {}), fieldKey: const Key('chat-search')),
              if (_picked.isNotEmpty) ...[
                const SizedBox(height: 10),
                Wrap(spacing: 6, runSpacing: 6, children: [
                  for (final p in _picked)
                    StatusChip(p.name, bg: Ms.primary100, fg: Ms.primary, outline: Ms.primary, onRemove: () => _toggle(p)),
                ]),
              ],
              if (!_add && _picked.length >= 2) ...[
                const SizedBox(height: 12),
                const MsLabel('그룹 이름'),
                const SizedBox(height: 6),
                MsInput(controller: _title, hint: '비우면 참여자 이름으로 보여요', fieldKey: const Key('chat-group-title')),
              ],
              if (_picked.isNotEmpty || _add) ...[
                const SizedBox(height: 10),
                Text(_guide, style: Typo.caption500.copyWith(color: Ms.gray600)),
              ],
            ]),
          ),
          Expanded(
            child: people == null
                ? Center(
                    child: _error != null
                        ? Text(_error!, style: Typo.body400.copyWith(color: Ms.gray600))
                        : const CircularProgressIndicator(strokeWidth: 2))
                : shown.isEmpty
                    ? Center(child: Text('찾는 직원이 없어요', style: Typo.body400.copyWith(color: Ms.gray600)))
                    : ListView.separated(
                        padding: const EdgeInsets.all(16),
                        itemCount: shown.length,
                        separatorBuilder: (_, _) => const SizedBox(height: 8),
                        itemBuilder: (context, i) {
                          final p = shown[i];
                          final joined = members.contains(p.id);
                          final on = _picked.any((x) => x.id == p.id);
                          final full = !on && _picked.length >= _cap;
                          final enabled = !joined && !full;
                          return Opacity(
                            opacity: joined ? 0.5 : 1,
                            child: MsCard(
                              selected: on,
                              onTap: enabled || on ? () => _toggle(p) : null,
                              child: Row(children: [
                                MsCheckbox(on || joined, enabled: enabled || on),
                                const SizedBox(width: 12),
                                // 이름 + 배지 = 남는 폭(이름만 줄임표) · 「이미 참여 중」 = 늘 오른쪽 끝(F10)
                                Expanded(
                                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                                    Flexible(child: Text(p.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.body600)),
                                    const SizedBox(width: 6),
                                    roleBadge(p.role),
                                  ]),
                                ),
                                if (joined) const MiniChip('이미 참여 중', Ms.gray200, Ms.gray600),
                              ]),
                            ),
                          );
                        },
                      ),
          ),
        ]),
      ),
    );
  }
}

// 새 대화 열기 — 폰 = 채팅 탭 스택에 · 아이패드 = 가운데 창. 성공하면 그 방
Future<Room?> pickNewChat(BuildContext context) {
  if (isTabletWidth(context)) return showCenterPanel<Room>(context, const ChatPeopleScreen());
  return Navigator.of(context).push<Room>(MaterialPageRoute(fullscreenDialog: true, builder: (_) => const ChatPeopleScreen()));
}
