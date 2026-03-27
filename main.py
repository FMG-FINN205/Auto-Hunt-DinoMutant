from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

try:
    from .function import AdbClient, ImageMatcher, MatchResult, Settings, inside_circle, resolve_path, safe_sleep
except ImportError:  # chạy trực tiếp hoặc sau khi đóng gói .exe
    from function import AdbClient, ImageMatcher, MatchResult, Settings, inside_circle, resolve_path, safe_sleep


Point = Tuple[int, int]
ROI = Tuple[int, int, int, int]


# ═══════════════════════════════════════════════════════════════════════════════
#  Stats
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Stats:
    success_total: int = 0
    success_since_step5: int = 0
    step5_runs: int = 0
    fail_streak: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
#  AutoHunter
# ═══════════════════════════════════════════════════════════════════════════════

class AutoHunter:
    def __init__(
        self,
        settings: Settings,
        log: Callable[[str], None],
        on_stats: Callable[[Stats], None],
    ):
        self.s = settings
        self.log = log
        self.on_stats = on_stats
        self.stats = Stats()

        adb_path = resolve_path(self.s.get("adb", "adb_path", default="ADB/adb.exe"))
        self.adb = AdbClient(adb_path)
        self.matcher = ImageMatcher()

        self.forbidden: List[Point] = []

    # ── Helpers đọc setting ──────────────────────────────────────────────────

    def _thr(self, name: str) -> float:
        return float(self.s.get("thresholds", name, default=self.s.get("thresholds", "default", default=0.85)))

    def _tmpl(self, name: str) -> Optional[str]:
        p = self.s.get("templates", name, default=None)
        if not p:
            return None
        return resolve_path(str(p))

    def _roi(self, name: str) -> ROI:
        v = self.s.get("rois", name, default=[0, 0, 0, 0])
        return int(v[0]), int(v[1]), int(v[2]), int(v[3])

    def _coord(self, name: str) -> Point:
        v = self.s.get("coords", name, default=[0, 0])
        return int(v[0]), int(v[1])

    def _delay(self, name: str) -> float:
        return float(self.s.get("delays_s", name, default=0.0))

    def _hold(self, name: str) -> int:
        return int(self.s.get("hold_ms", name, default=self.s.get("hold_ms", "default", default=60)))

    def _tap(self, serial: str, p: Point, hold_key: str, stop_event) -> bool:
        if stop_event.is_set():
            return True
        self.adb.tap_hold(serial, p[0], p[1], self._hold(hold_key))
        return safe_sleep(stop_event, self._delay("after_click"))

    def _after_map_switch(self, stop_event) -> bool:
        return safe_sleep(stop_event, self._delay("after_map_switch"))

    def _find(
        self,
        serial: str,
        screenshot,
        template_name: str,
        roi_name: Optional[str],
    ) -> Optional[MatchResult]:
        path = self._tmpl(template_name)
        if not path:
            return None
        roi = self._roi(roi_name) if roi_name else None
        return self.matcher.match(screenshot, path, self._thr(template_name), roi=roi)

    def _match_any_dino(self, serial: str, screenshot) -> Optional[Tuple[str, MatchResult]]:
        for name in ["Dino1", "Dino2"]:
            r = self._find(serial, screenshot, name, "vung_san")
            if r and r.found and r.center:
                radius = int(self.s.get("forbidden", "radius_px", default=50))
                if any(inside_circle(r.center, c, radius) for c in self.forbidden):
                    continue
                return name, r
        return None

    # ── Step 1: đóng cửa sổ X ───────────────────────────────────────────────

    def _check_x_and_close(self, serial: str, stop_event) -> bool:
        x_tmpl = self._tmpl("X")
        if not x_tmpl:
            return False
        while not stop_event.is_set():
            shot = self.adb.screenshot(serial)
            safe_sleep(stop_event, self._delay("after_screenshot"))
            r = self._find(serial, shot, "X", "check_x")
            if not r or not r.found or not r.center:
                return False
            self.log(f"Thấy X (score {r.score:.2f}) -> click đóng")
            if self._tap(serial, r.center, "click_x", stop_event):
                return True
        return True

    # ── Step 1b: kiểm tra home, đảo map ─────────────────────────────────────

    def _maybe_home(self, serial: str, stop_event) -> bool:
        shot = self.adb.screenshot(serial)
        safe_sleep(stop_event, self._delay("after_screenshot"))
        r = self._find(serial, shot, "Home", "home")
        if r and r.found:
            self.log(f"Đang ở Home (score {r.score:.2f}) -> đảo map")
            return self._tap(serial, self._coord("dao_map"), "click_map", stop_event)
        return False

    # ── Step 2: chọn dino ────────────────────────────────────────────────────

    def _step2_pick_dino(self, serial: str, stop_event) -> Optional[Point]:
        rx1, ry1, rx2, ry2 = self._roi("vung_san")
        if rx1 == 0 and ry1 == 0 and rx2 == 0 and ry2 == 0:
            self.log(
                "ROI 'vùng săn' đang = (0,0,0,0) -> tool sẽ không thể quét dino. "
                "Hãy vào Setting và 'Chụp & vẽ ROI'."
            )
            safe_sleep(stop_event, 0.8)
            return None

        max_scan = int(self.s.get("logic", "max_scan_no_dino", default=3))
        for attempt in range(1, max_scan + 1):
            if stop_event.is_set():
                return None
            shot = self.adb.screenshot(serial)
            safe_sleep(stop_event, self._delay("after_screenshot"))
            found = self._match_any_dino(serial, shot)
            if found:
                name, r = found
                self.log(f"Tìm thấy {name} (score {r.score:.2f}) -> click")
                if r.center and self._tap(serial, r.center, "click_dino", stop_event):
                    return None
                return r.center
            # Diagnostic: hiển thị score để dễ tinh chỉnh ngưỡng
            r1 = self._find(serial, shot, "Dino1", "vung_san")
            r2 = self._find(serial, shot, "Dino2", "vung_san")
            s1 = r1.score if r1 else 0.0
            s2 = r2.score if r2 else 0.0
            t1 = self._thr("Dino1")
            t2 = self._thr("Dino2")
            self.log(
                f"Không thấy dino (lần {attempt}/{max_scan}) | "
                f"score Dino1={s1:.2f} (thr {t1:.2f}), Dino2={s2:.2f} (thr {t2:.2f})"
            )
            if safe_sleep(stop_event, self._delay("between_scans")):
                return None

        self.log("Không có dino sau 3 lần -> đảo map")
        self._tap(serial, self._coord("dao_map"), "click_map", stop_event)
        self.log("Đã click đảo map -> quay lại bước 1")
        self._after_map_switch(stop_event)
        return None

    # ── Step 3: tìm nút Hunt1 ────────────────────────────────────────────────

    def _step3_find_hunt_button(self, serial: str, dino_center: Point, stop_event) -> bool:
        shot = self.adb.screenshot(serial)
        safe_sleep(stop_event, self._delay("after_screenshot"))
        r = self._find(serial, shot, "Hunt1", "vung_san")
        if r and r.found and r.center:
            self.log(f"Thấy Hunt1 (score {r.score:.2f}) -> click")
            return not self._tap(serial, r.center, "click_hunt_btn", stop_event)

        radius = int(self.s.get("forbidden", "radius_px", default=50))
        self.forbidden.append(dino_center)
        self.log(f"Không thấy Hunt1 -> tạo vùng cấm radius={radius}px và quay lại chọn dino")
        return False

    # ── Step 4: hunt và kiểm tra thành công ─────────────────────────────────

    def _step4_hunt_and_check_success(self, serial: str, stop_event) -> bool:
        self.log("Click tọa độ 'hunt' và kiểm tra X...")
        if self._tap(serial, self._coord("hunt"), "click_hunt_coord", stop_event):
            return False

        shot = self.adb.screenshot(serial)
        safe_sleep(stop_event, self._delay("after_screenshot"))
        r = self._find(serial, shot, "X", "check_x")
        if not r or not r.found:
            return True

        self.log("Hunt bị chặn (có X) -> đóng X và quay lại")
        self._check_x_and_close(serial, stop_event)
        return False

    # ── Step 6: mở thư và claim ──────────────────────────────────────────────

    def _step6_claim(self, serial: str, stop_event) -> None:
        self.log("Step6: mở thư và claim...")
        claimall_ok = False
        claim_ok = False
        while not stop_event.is_set() and (not claimall_ok or not claim_ok):
            self._tap(serial, self._coord("thu"), "click_mail", stop_event)
            shot = self.adb.screenshot(serial)
            safe_sleep(stop_event, self._delay("after_screenshot"))

            r_all = self._find(serial, shot, "Claimall", "claim")
            if r_all and r_all.found and r_all.center:
                self.log("Thấy Claimall -> click")
                self._tap(serial, r_all.center, "click_claim", stop_event)
                claimall_ok = True
            else:
                self.log("Chưa thấy Claimall -> thử lại")

            shot2 = self.adb.screenshot(serial)
            safe_sleep(stop_event, self._delay("after_screenshot"))
            r = self._find(serial, shot2, "Claim", "claim")
            if r and r.found and r.center:
                self.log("Thấy Claim -> click")
                self._tap(serial, r.center, "click_claim", stop_event)
                claim_ok = True
            else:
                self.log("Chưa thấy Claim -> thử lại")

            safe_sleep(stop_event, self._delay("between_scans"))

        if claimall_ok and claim_ok:
            self.log("Claim xong -> quay lại step1")

    # ── Step 7: reset mạng ───────────────────────────────────────────────────

    def _step7_reset_network(self, serial: str, stop_event) -> None:
        self.log("Fail streak > ngưỡng -> tìm Reset toàn màn hình...")
        while not stop_event.is_set():
            shot = self.adb.screenshot(serial)
            safe_sleep(stop_event, self._delay("after_screenshot"))
            r = self._find(serial, shot, "Reset", None)
            if r and r.found and r.center:
                self.log(f"Thấy Reset (score {r.score:.2f}) -> click")
                self._tap(serial, r.center, "click_reset", stop_event)
                return
            self.log("Chưa thấy Reset -> quét lại")
            safe_sleep(stop_event, self._delay("between_scans"))

    # ── Vòng lặp chính ───────────────────────────────────────────────────────

    def run(self, serial: str, stop_event) -> None:
        self.log(f"Bắt đầu chạy với thiết bị: {serial}")
        self.forbidden.clear()
        self.stats = Stats()
        self.on_stats(self.stats)

        while not stop_event.is_set():
            # Step 7: reset khi fail liên tục
            if self.stats.fail_streak > int(self.s.get("logic", "fail_reset_threshold", default=10)):
                self._step7_reset_network(serial, stop_event)
                self.stats.fail_streak = 0
                self.on_stats(self.stats)

            # Step 1: đóng X
            if self._check_x_and_close(serial, stop_event):
                break
            if stop_event.is_set():
                break

            # Step 1b: về home thì đảo map
            self._maybe_home(serial, stop_event)
            if stop_event.is_set():
                break

            # Step 2: chọn dino
            dino_center = self._step2_pick_dino(serial, stop_event)
            if stop_event.is_set():
                break
            if not dino_center:
                continue

            # Step 3: tìm nút Hunt1
            ok_hunt_btn = self._step3_find_hunt_button(serial, dino_center, stop_event)
            if stop_event.is_set():
                break
            if not ok_hunt_btn:
                continue

            # Step 4: hunt và kiểm tra
            success = self._step4_hunt_and_check_success(serial, stop_event)
            if stop_event.is_set():
                break

            if success:
                self.stats.success_total += 1
                self.stats.success_since_step5 += 1
                self.stats.fail_streak = 0
                self.forbidden.clear()
                self.log(f"Săn thành công! Tổng: {self.stats.success_total}")
                self.on_stats(self.stats)

                # Step 5: đảo map sau N lần thành công
                need_step5 = self.stats.success_since_step5 >= int(
                    self.s.get("logic", "success_before_step5", default=4)
                )
                if need_step5:
                    self.stats.success_since_step5 = 0
                    self.stats.step5_runs += 1
                    self.on_stats(self.stats)
                    self.log(
                        f"Step5: đảo map "
                        f"(lần {self.stats.step5_runs}/"
                        f"{int(self.s.get('logic','step5_before_step6',default=5))})"
                    )
                    self._tap(serial, self._coord("dao_map"), "click_map", stop_event)
                    self.log("Đã click đảo map (Step5) -> quay lại bước 1")
                    self._after_map_switch(stop_event)

                # Step 6: claim sau M lần đảo map
                if self.stats.step5_runs >= int(self.s.get("logic", "step5_before_step6", default=5)):
                    self.stats.step5_runs = 0
                    self.on_stats(self.stats)
                    self._step6_claim(serial, stop_event)
                    self.log("Đã claim xong -> quay lại bước 1")

                if need_step5 or self.stats.step5_runs == 0:
                    continue

            else:
                self.stats.fail_streak += 1
                self.on_stats(self.stats)
                self.log(f"Săn thất bại (fail streak: {self.stats.fail_streak})")