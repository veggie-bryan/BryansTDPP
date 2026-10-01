import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
import os
import math

import sys
import clr
from System import *
from System.Collections.Generic import List

sys.path.append(r"C:\Windows\Microsoft.NET\assembly\GAC_MSIL\OpenTDv242\v4.0_24.2.0.0__65e6d95ed5c2e178")
sys.path.append(r"C:\Windows\Microsoft.NET\assembly\GAC_MSIL\OpenTDv242.CoSolver\v4.0_24.2.0.0__65e6d95ed5c2e178")
sys.path.append(r"C:\Windows\Microsoft.NET\assembly\GAC_64\OpenTDv242.Results\v4.0_24.2.0.0__b62f614be6a1e14a")
clr.AddReference("OpenTDv242")
clr.AddReference("OpenTDv242.CoSolver")
clr.AddReference("OpenTDv242.Results")
from OpenTDv242 import *
from OpenTDv242.CoSolver import *
from OpenTDv242.Results.Dataset import SaveFile, ItemIdentifierCollection, DataTypes, StandardDataSubtypes


""" SAV FILE INPUTS ========================================================================================="""

sav_files = [
    r"Path\To\File.sav"
]

""" OUTPUT FILE =============================================================================================="""

excel_file = r'Path\To\Results.xlsx'

""" ANALYSIS OPTIONS ========================================================================================="""

USE_QUASI_STEADY_STATE_ONLY = False

# Orbit period in seconds (only used if USE_QUASI_STEADY_STATE_ONLY = True)
ORBIT_PERIOD_SECONDS = 5639
NUM_FINAL_ORBITS = 5

""" HEATER REGISTER OPTIONS =================================================================================="""

PULL_HEATER_DATA = True

HEATER_REGISTER_NAMES = [
    "XXXXX",
    "XXXXX",
    "XXXXX"
]

DUTY_CYCLE_WARNING_THRESHOLD = 80  # % - highlighted red in Excel if exceeded

""" PLOTTING INPUTS =========================================================================================="""

GENERATE_PLOTS = False
PLOT_OUTPUT_DIR = r'Path\To\PlotsFolder'

# Define submodels and their node groupings
# Format: {submodel_name: {group_name: [node_ids]}}
SUBMODELS_TO_PLOT = {
    'SUBMODEL': {
        'SUBMODEL_NAME or NODE_LIST_NAME': list(range(1, 57)) # can be used to plot submodel temps OR specfic section i.e. solar_arrays submodel can be breaken into a -X and +X array
    }
}

# NEED TO ADD I/O FEATURE TO TEMP STABILITY PLOTS
STABILITY_THRESHOLD = 0.001

"""==========================================================================================================="""

all_results = {}
all_submodels = set()
heater_data = {}
heater_results = {}
raw_data = {}
all_heater_registers = set()
times_data = {}

for sav in sav_files:
    case_name = os.path.basename(sav)
    print(f"Processing: {case_name}")

    data = SaveFile(sav)

    submodels = list(data.GetThermalSubmodels())
    times = data.GetTimes().GetValues()
    times_data[case_name] = times

    if USE_QUASI_STEADY_STATE_ONLY:
        total_time = times[len(times) - 1]
        analysis_start_time = total_time - (NUM_FINAL_ORBITS * ORBIT_PERIOD_SECONDS)
    else:
        analysis_start_time = 0

    raw_data[case_name] = {}

    for submodel in submodels:
        node_ids = list(data.GetNodeIds(submodel))

        if len(node_ids) == 0:
            continue

        all_submodels.add(submodel)

        node_names = [f"{submodel}.T{node_id}" for node_id in node_ids]

        temps = data.GetData(*node_names)
        temp_values = temps.GetValues(Units.SI)  # Kelvin

        raw_data[case_name][submodel] = {}
        for i, node_name in enumerate(node_names):
            temps_celsius = [t - 273.15 if not float('nan') == t else None for t in temp_values[i]]
            raw_data[case_name][submodel][node_name] = temps_celsius

        all_temps_in_window = []
        for node_temps in temp_values:
            for i, temp in enumerate(node_temps):
                if times[i] >= analysis_start_time and not float('nan') == temp:
                    all_temps_in_window.append(temp)

        if len(all_temps_in_window) == 0:
            continue

        min_temp = min(all_temps_in_window) - 273.15
        max_temp = max(all_temps_in_window) - 273.15

        if submodel not in all_results:
            all_results[submodel] = {}

        all_results[submodel][case_name] = {
            'min_temp': round(min_temp, 2),
            'max_temp': round(max_temp, 2),
            'num_nodes': len(temp_values)
        }

    # Duty Cycle
    if PULL_HEATER_DATA:
        heater_data[case_name] = {}

        for heater_handle in HEATER_REGISTER_NAMES:
            reg_full_name = f"OT{heater_handle}"

            try:
                reg_dataset = data.GetRegisterData(reg_full_name)
                reg_values_all = reg_dataset.GetValues(Units.SI)
                reg_values = [v if not math.isnan(v) else None for v in reg_values_all]
            except Exception as e:
                print(f"  Could not read register '{reg_full_name}': {e}")
                continue

            all_heater_registers.add(heater_handle)
            heater_data[case_name][heater_handle] = reg_values

            # Duty Cycle = On Time / Total Time, using the OT accumulator delta
            filtered = [(t, v) for t, v in zip(times, reg_values) if t >= analysis_start_time and v is not None]

            if len(filtered) < 2:
                continue

            t_start, ot_start = filtered[0]
            t_end, ot_end = filtered[-1]
            window_duration_s = t_end - t_start
            on_time_s = ot_end - ot_start
            duty_cycle_pct = (on_time_s / window_duration_s) * 100 if window_duration_s > 0 else None

            if duty_cycle_pct is None:
                continue

            heater_results.setdefault(heater_handle, {})[case_name] = {
                'duty_cycle_pct': round(duty_cycle_pct, 2),
                'on_time_s': round(on_time_s, 1),
                'window_duration_s': round(window_duration_s, 1),
            }

print("All cases processed.")


"""CALCULATE AVERAGED GROUP STATISTICS + MIN/MAX NODE TRACKING"""

grouped_data = {}
min_node_data = {}
max_node_data = {}

for sav in sav_files:
    case_name = os.path.basename(sav)
    grouped_data[case_name] = {}
    min_node_data[case_name] = {}
    max_node_data[case_name] = {}

    for submodel, groups in SUBMODELS_TO_PLOT.items():
        if case_name not in raw_data or submodel not in raw_data[case_name]:
            continue

        times = times_data[case_name]
        node_data = raw_data[case_name][submodel]

        grouped_data[case_name][submodel] = {}
        min_node_data[case_name][submodel] = {}
        max_node_data[case_name][submodel] = {}

        for group_name, node_ids in groups.items():
            group_nodes = {}
            for node_name, temps in node_data.items():
                node_id = int(node_name.split('.T')[1])
                if node_id in node_ids:
                    group_nodes[node_name] = temps

            if not group_nodes:
                continue

            avg_temps = []
            for i in range(len(times)):
                temps_at_this_time = []
                for node_temps in group_nodes.values():
                    if i < len(node_temps) and node_temps[i] is not None:
                        temps_at_this_time.append(node_temps[i])

                if temps_at_this_time:
                    avg_temps.append(sum(temps_at_this_time) / len(temps_at_this_time))
                else:
                    avg_temps.append(None)

            grouped_data[case_name][submodel][group_name] = avg_temps

            times_list = list(times)
            total_time = times_list[-1]
            analysis_start_time = total_time - (NUM_FINAL_ORBITS * ORBIT_PERIOD_SECONDS)

            node_avg_temps = {}
            for node_name, node_temps in group_nodes.items():
                temps_in_window = []
                for i, temp in enumerate(node_temps):
                    if times_list[i] >= analysis_start_time and temp is not None:
                        temps_in_window.append(temp)

                if temps_in_window:
                    node_avg_temps[node_name] = sum(temps_in_window) / len(temps_in_window)

            if node_avg_temps:
                coldest_node = min(node_avg_temps, key=node_avg_temps.get)
                hottest_node = max(node_avg_temps, key=node_avg_temps.get)

                min_node_data[case_name][submodel][group_name] = {
                    'node_name': coldest_node,
                    'temps': group_nodes[coldest_node],
                    'avg_temp': node_avg_temps[coldest_node]
                }

                max_node_data[case_name][submodel][group_name] = {
                    'node_name': hottest_node,
                    'temps': group_nodes[hottest_node],
                    'avg_temp': node_avg_temps[hottest_node]
                }


"""PLOTTING (OPTIONAL - SKIP IF GENERATE_PLOTS = False)"""

if GENERATE_PLOTS:
    import matplotlib.pyplot as plt
    import matplotlib
    import numpy as np
    matplotlib.use('Agg')

    os.makedirs(PLOT_OUTPUT_DIR, exist_ok=True)

    for submodel, groups in SUBMODELS_TO_PLOT.items():
        for sav in sav_files:
            case_name = os.path.basename(sav)
            case_name_clean = case_name.replace('.sav', '')

            if case_name not in grouped_data or submodel not in grouped_data[case_name]:
                continue

            times = times_data[case_name]
            times_list = list(times)

            fig1, ax1 = plt.subplots(figsize=(14, 7))
            fig2, ax2 = plt.subplots(figsize=(14, 7))

            for group_name, avg_temps in grouped_data[case_name][submodel].items():

                min_node_info = min_node_data[case_name][submodel].get(group_name)
                max_node_info = max_node_data[case_name][submodel].get(group_name)

                if not min_node_info or not max_node_info:
                    continue

                min_node_name = min_node_info['node_name']
                min_node_temps = min_node_info['temps']
                min_node_avg = min_node_info['avg_temp']

                max_node_name = max_node_info['node_name']
                max_node_temps = max_node_info['temps']
                max_node_avg = max_node_info['avg_temp']

                node_data = raw_data[case_name][submodel]
                group_nodes = {}
                for node_name, temps in node_data.items():
                    node_id = int(node_name.split('.T')[1])
                    if node_id in groups[group_name]:
                        group_nodes[node_name] = temps

                def detect_stable_regions_reference_based(temps_arr, threshold=STABILITY_THRESHOLD):
                    stable_mask = np.zeros(len(temps_arr), dtype=bool)

                    if len(temps_arr) < 2:
                        return stable_mask

                    in_stable_window = False
                    reference_temp = None

                    for i in range(len(temps_arr)):
                        if not in_stable_window:
                            reference_temp = temps_arr[i]
                            in_stable_window = True
                            stable_mask[i] = True
                        else:
                            delta = abs(temps_arr[i] - reference_temp)
                            if delta <= threshold:
                                stable_mask[i] = True
                            else:
                                stable_mask[i] = False
                                in_stable_window = False

                    return stable_mask

                valid_data_avg = [(t, temp) for t, temp in zip(times_list, avg_temps) if temp is not None]
                valid_data_min = [(t, temp) for t, temp in zip(times_list, min_node_temps) if temp is not None]
                valid_data_max = [(t, temp) for t, temp in zip(times_list, max_node_temps) if temp is not None]

                if valid_data_avg and valid_data_min and valid_data_max:
                    plot_times_avg, plot_temps_avg = zip(*valid_data_avg)
                    plot_times_min, plot_temps_min = zip(*valid_data_min)
                    plot_times_max, plot_temps_max = zip(*valid_data_max)

                    times_arr = np.array(plot_times_avg)
                    avg_arr = np.array(plot_temps_avg)
                    min_arr = np.array(plot_temps_min)
                    max_arr = np.array(plot_temps_max)

                    all_node_stable_masks = []
                    for node_name, node_temps in group_nodes.items():
                        valid_node_data = [temp for temp in node_temps if temp is not None]
                        if len(valid_node_data) > 0:
                            node_arr = np.array(valid_node_data)
                            node_stable_mask = detect_stable_regions_reference_based(node_arr)
                            all_node_stable_masks.append(node_stable_mask)

                    if all_node_stable_masks:
                        stable_mask_combined = np.ones(len(all_node_stable_masks[0]), dtype=bool)
                        for mask in all_node_stable_masks:
                            stable_mask_combined = stable_mask_combined & mask
                    else:
                        stable_mask_combined = np.zeros(len(times_arr), dtype=bool)

                    in_stable_region = False
                    stable_start = None

                    for i in range(len(times_arr)):
                        if i < len(stable_mask_combined) and stable_mask_combined[i] and not in_stable_region:
                            stable_start = times_arr[i]
                            in_stable_region = True
                        elif (i >= len(stable_mask_combined) or not stable_mask_combined[i]) and in_stable_region:
                            ax1.axvspan(stable_start, times_arr[i-1], alpha=0.15, color='green', zorder=1)
                            in_stable_region = False

                    if in_stable_region:
                        ax1.axvspan(stable_start, times_arr[-1], alpha=0.15, color='green', zorder=1)

                    ax1.plot(times_arr, avg_arr, linewidth=2.5, color='#1f77b4',
                            label=f'{group_name} Average', zorder=3)
                    ax1.plot(times_arr, min_arr, linewidth=1.5, color='#2ca02c',
                            label=f'Coldest Node ({min_node_name.split(".T")[1]}) - Avg: {min_node_avg:.2f}°C',
                            linestyle='--', zorder=2)
                    ax1.plot(times_arr, max_arr, linewidth=1.5, color='#d62728',
                            label=f'Hottest Node ({max_node_name.split(".T")[1]}) - Avg: {max_node_avg:.2f}°C',
                            linestyle='--', zorder=2)

                    from matplotlib.patches import Patch
                    stable_patch = Patch(facecolor='green', alpha=0.15,
                                        label=f'All {len(group_nodes)} Nodes Stable (±{STABILITY_THRESHOLD}°C)')
                    handles, labels = ax1.get_legend_handles_labels()
                    handles.append(stable_patch)
                    ax1.legend(handles=handles, loc='best', fontsize=9, framealpha=0.9)

                    stability_pct = (np.sum(stable_mask_combined) / len(stable_mask_combined)) * 100 if len(stable_mask_combined) > 0 else 0

                    stability_text = f"Stability Analysis:\n"
                    stability_text += f"Threshold: ±{STABILITY_THRESHOLD}°C from window start\n"
                    stability_text += f"Nodes Checked: {len(group_nodes)}\n"
                    stability_text += f"All Stable: {stability_pct:.1f}% of mission"

                    props = dict(boxstyle='round', facecolor='lightgreen' if stability_pct > 80 else 'wheat', alpha=0.8)
                    ax1.text(0.02, 0.98, stability_text, transform=ax1.transAxes, fontsize=9,
                            verticalalignment='top', horizontalalignment='left', bbox=props, family='monospace')

                total_time = times_list[-1]
                final_orbits_start_time = total_time - (NUM_FINAL_ORBITS * ORBIT_PERIOD_SECONDS)

                valid_data_avg_final = [(t, temp) for t, temp in zip(times_list, avg_temps)
                                       if t >= final_orbits_start_time and temp is not None]
                valid_data_min_final = [(t, temp) for t, temp in zip(times_list, min_node_temps)
                                       if t >= final_orbits_start_time and temp is not None]
                valid_data_max_final = [(t, temp) for t, temp in zip(times_list, max_node_temps)
                                       if t >= final_orbits_start_time and temp is not None]

                if valid_data_avg_final and valid_data_min_final and valid_data_max_final:
                    plot_times_avg_final, plot_temps_avg_final = zip(*valid_data_avg_final)
                    plot_times_min_final, plot_temps_min_final = zip(*valid_data_min_final)
                    plot_times_max_final, plot_temps_max_final = zip(*valid_data_max_final)

                    times_arr_final = np.array([t - final_orbits_start_time for t in plot_times_avg_final])
                    avg_arr_final = np.array(plot_temps_avg_final)
                    min_arr_final = np.array(plot_temps_min_final)
                    max_arr_final = np.array(plot_temps_max_final)

                    all_node_stable_masks_final = []
                    for node_name, node_temps in group_nodes.items():
                        valid_node_data_final = [temp for i, temp in enumerate(node_temps)
                                                if i < len(times_list) and times_list[i] >= final_orbits_start_time and temp is not None]
                        if len(valid_node_data_final) > 0:
                            node_arr_final = np.array(valid_node_data_final)
                            node_stable_mask_final = detect_stable_regions_reference_based(node_arr_final)
                            all_node_stable_masks_final.append(node_stable_mask_final)

                    if all_node_stable_masks_final:
                        stable_mask_combined_final = np.ones(len(all_node_stable_masks_final[0]), dtype=bool)
                        for mask in all_node_stable_masks_final:
                            stable_mask_combined_final = stable_mask_combined_final & mask
                    else:
                        stable_mask_combined_final = np.zeros(len(times_arr_final), dtype=bool)

                    in_stable_region = False
                    stable_start = None

                    for i in range(len(times_arr_final)):
                        if i < len(stable_mask_combined_final) and stable_mask_combined_final[i] and not in_stable_region:
                            stable_start = times_arr_final[i]
                            in_stable_region = True
                        elif (i >= len(stable_mask_combined_final) or not stable_mask_combined_final[i]) and in_stable_region:
                            ax2.axvspan(stable_start, times_arr_final[i-1], alpha=0.15, color='green', zorder=1)
                            in_stable_region = False

                    if in_stable_region:
                        ax2.axvspan(stable_start, times_arr_final[-1], alpha=0.15, color='green', zorder=1)

                    ax2.plot(times_arr_final, avg_arr_final, linewidth=2.5, color='#1f77b4',
                            label=f'{group_name} Average', zorder=3)
                    ax2.plot(times_arr_final, min_arr_final, linewidth=1.5, color='#2ca02c',
                            label=f'Coldest Node ({min_node_name.split(".T")[1]})',
                            linestyle='--', zorder=2)
                    ax2.plot(times_arr_final, max_arr_final, linewidth=1.5, color='#d62728',
                            label=f'Hottest Node ({max_node_name.split(".T")[1]})',
                            linestyle='--', zorder=2)

                    stable_patch = Patch(facecolor='green', alpha=0.15,
                                        label=f'All {len(group_nodes)} Nodes Stable (±{STABILITY_THRESHOLD}°C)')
                    handles, labels = ax2.get_legend_handles_labels()
                    handles.append(stable_patch)
                    ax2.legend(handles=handles, loc='best', fontsize=9, framealpha=0.9)

                    stability_pct_final = (np.sum(stable_mask_combined_final) / len(stable_mask_combined_final)) * 100 if len(stable_mask_combined_final) > 0 else 0

                    stability_text = f"Stability Analysis:\n"
                    stability_text += f"Threshold: ±{STABILITY_THRESHOLD}°C from window start\n"
                    stability_text += f"Nodes Checked: {len(group_nodes)}\n"
                    stability_text += f"All Stable: {stability_pct_final:.1f}% of final {NUM_FINAL_ORBITS} orbits"

                    props = dict(boxstyle='round', facecolor='lightgreen' if stability_pct_final > 80 else 'wheat', alpha=0.8)
                    ax2.text(0.02, 0.98, stability_text, transform=ax2.transAxes, fontsize=9,
                            verticalalignment='top', horizontalalignment='left', bbox=props, family='monospace')

            ax1.set_xlabel('Time (s)', fontsize=12, fontweight='bold')
            ax1.set_ylabel('Temperature (°C)', fontsize=12, fontweight='bold')
            ax1.set_title(f'{submodel} - {case_name_clean}\nTemperature vs Time (Full Mission)',
                        fontsize=14, fontweight='bold')
            ax1.grid(True, alpha=0.3, linestyle='--')
            ax1.set_xlim(left=0, right=times_list[-1])
            ax1.margins(x=0)

            plot1_filename = os.path.join(PLOT_OUTPUT_DIR, f'{case_name_clean}_{submodel}_full.png')
            fig1.tight_layout()
            fig1.savefig(plot1_filename, dpi=200, bbox_inches='tight')
            plt.close(fig1)

            ax2.set_xlabel(f'Time in Final {NUM_FINAL_ORBITS} Orbits (s)', fontsize=12, fontweight='bold')
            ax2.set_ylabel('Temperature (°C)', fontsize=12, fontweight='bold')
            ax2.set_title(f'{submodel} - {case_name_clean}\nTemperature vs Time (Final {NUM_FINAL_ORBITS} Orbits - Quasi-Steady State)',
                        fontsize=14, fontweight='bold')
            ax2.grid(True, alpha=0.3, linestyle='--')
            ax2.set_xlim(left=0, right=NUM_FINAL_ORBITS * ORBIT_PERIOD_SECONDS)
            ax2.margins(x=0)

            plot2_filename = os.path.join(PLOT_OUTPUT_DIR, f'{case_name_clean}_{submodel}_final_orbit.png')
            fig2.tight_layout()
            fig2.savefig(plot2_filename, dpi=200, bbox_inches='tight')
            plt.close(fig2)

    print(f"Plots saved to: {PLOT_OUTPUT_DIR}")


""" EXCEL RESULTS """

existing_margins_op_limits = {}
existing_op_limits_library = {}

try:
    wb = openpyxl.load_workbook(excel_file)

    if "Margins" in wb.sheetnames:
        ws_margins_old = wb["Margins"]
        if ws_margins_old.max_row >= 3:
            for row in range(3, ws_margins_old.max_row + 1):
                submodel = ws_margins_old.cell(row=row, column=1).value
                op_min = ws_margins_old.cell(row=row, column=2).value
                op_max = ws_margins_old.cell(row=row, column=3).value
                if submodel:
                    existing_margins_op_limits[submodel] = {
                        'min': op_min if op_min not in [None, ''] else None,
                        'max': op_max if op_max not in [None, ''] else None
                    }

    if "Op Limits" in wb.sheetnames:
        ws_op_limits_old = wb["Op Limits"]
        if ws_op_limits_old.max_row >= 2:
            header_row = 2
            limit_set_names = []
            for col in range(2, ws_op_limits_old.max_column + 1, 2):
                limit_name = ws_op_limits_old.cell(row=header_row, column=col).value
                if limit_name and limit_name.endswith(' Min'):
                    limit_set_names.append(limit_name.replace(' Min', ''))

            for row in range(3, ws_op_limits_old.max_row + 1):
                submodel = ws_op_limits_old.cell(row=row, column=1).value
                if submodel:
                    existing_op_limits_library[submodel] = {}
                    for i, limit_set in enumerate(limit_set_names):
                        min_col = 2 + (i * 2)
                        max_col = min_col + 1
                        op_min = ws_op_limits_old.cell(row=row, column=min_col).value
                        op_max = ws_op_limits_old.cell(row=row, column=max_col).value
                        existing_op_limits_library[submodel][limit_set] = {
                            'min': op_min if op_min not in [None, ''] else None,
                            'max': op_max if op_max not in [None, ''] else None
                        }

    for sheet_name in wb.sheetnames:
        del wb[sheet_name]

except PermissionError:
    print(f"ERROR: Cannot access {excel_file} - close the file and try again.")
    exit()

except FileNotFoundError:
    wb = openpyxl.Workbook()
    if 'Sheet' in wb.sheetnames:
        del wb['Sheet']

# ============================================================================
# OP LIMITS LIBRARY SHEET
# ============================================================================
ws_op_limits = wb.create_sheet("Op Limits", 0)

sorted_submodels = sorted(all_submodels)

if existing_op_limits_library:
    all_limit_sets = set()
    for submodel_limits in existing_op_limits_library.values():
        all_limit_sets.update(submodel_limits.keys())
    limit_sets = sorted(all_limit_sets)
else:
    limit_sets = ['Limit Set 1', 'Limit Set 2', 'Limit Set 3', 'Limit Set 4', 'Limit Set 5']

ws_op_limits.append(['OPERATIONAL TEMPERATURE LIMITS LIBRARY - Edit column headers to name your limit sets'])
title_cell = ws_op_limits.cell(row=1, column=1)
title_cell.font = Font(bold=True, size=12, color="FFFFFF")
title_cell.fill = PatternFill(start_color="FF6600", end_color="FF6600", fill_type="solid")
title_cell.alignment = Alignment(horizontal='center', vertical='center')
ws_op_limits.merge_cells(start_row=1, start_column=1, end_row=1, end_column=1 + len(limit_sets) * 2)

header_row = ['Submodel']
for limit_set in limit_sets:
    header_row.extend([f'{limit_set} Min', f'{limit_set} Max'])
ws_op_limits.append(header_row)

for cell in ws_op_limits[2]:
    cell.font = Font(bold=True, size=10, color="000000")
    cell.fill = PatternFill(start_color="FFC000", end_color="FFC000", fill_type="solid")
    cell.alignment = Alignment(horizontal='center', vertical='center')

for submodel in sorted_submodels:
    row_data = [submodel]

    for limit_set in limit_sets:
        if submodel in existing_op_limits_library and limit_set in existing_op_limits_library[submodel]:
            op_min = existing_op_limits_library[submodel][limit_set]['min']
            op_max = existing_op_limits_library[submodel][limit_set]['max']
        else:
            op_min = ''
            op_max = ''
        row_data.extend([op_min, op_max])

    ws_op_limits.append(row_data)

for col_num in range(1, ws_op_limits.max_column + 1):
    column_letter = get_column_letter(col_num)
    max_length = 0
    for cell in ws_op_limits[column_letter]:
        try:
            if len(str(cell.value)) > max_length:
                max_length = len(str(cell.value))
        except:
            pass
    adjusted_width = min(max_length + 2, 30)
    ws_op_limits.column_dimensions[column_letter].width = adjusted_width

ws_op_limits.freeze_panes = 'B3'

# ============================================================================
# MARGINS SHEET
# ============================================================================
ws_margins = wb.create_sheet("Margins", 1)

row1_data = ['Submodel', 'Op Min (°C)', 'Op Max (°C)']
for case_name in sav_files:
    row1_data.extend([os.path.basename(case_name), '', '', ''])
ws_margins.append(row1_data)

row2_data = ['(Copy from Op Limits sheet)', '', '']
for _ in sav_files:
    row2_data.extend(['Min', 'Max', 'ΔMin', 'ΔMax'])
ws_margins.append(row2_data)

for cell in ws_margins[1]:
    cell.font = Font(bold=True, size=11, color="FFFFFF")
    cell.fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
    cell.alignment = Alignment(horizontal='center', vertical='center')

for cell in ws_margins[2]:
    cell.font = Font(bold=True, size=10, color="FFFFFF")
    cell.fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    cell.alignment = Alignment(horizontal='center', vertical='center')

col_idx = 4
for case_name in sav_files:
    ws_margins.merge_cells(start_row=1, start_column=col_idx, end_row=1, end_column=col_idx+3)
    col_idx += 4

for submodel in sorted_submodels:
    row_data = [submodel]

    if submodel in existing_margins_op_limits:
        op_min = existing_margins_op_limits[submodel]['min']
        op_max = existing_margins_op_limits[submodel]['max']
    else:
        op_min = ''
        op_max = ''
    row_data.extend([op_min, op_max])

    for sav in sav_files:
        case_name = os.path.basename(sav)

        if case_name in all_results.get(submodel, {}):
            case_data = all_results[submodel][case_name]
            min_temp = case_data['min_temp']
            max_temp = case_data['max_temp']

            delta_min = ''
            delta_max = ''
            if op_min not in ['', None]:
                delta_min = round(min_temp - float(op_min), 2)
            if op_max not in ['', None]:
                delta_max = round(float(op_max) - max_temp, 2)

            row_data.extend([min_temp, max_temp, delta_min, delta_max])
        else:
            row_data.extend(['', '', '', ''])

    ws_margins.append(row_data)

    row_num = ws_margins.max_row
    col_idx = 6

    for case_idx in range(len(sav_files)):
        delta_min_col = col_idx + (case_idx * 4)
        delta_max_col = delta_min_col + 1

        delta_min_cell = ws_margins.cell(row=row_num, column=delta_min_col)
        if delta_min_cell.value not in ['', None]:
            val = float(delta_min_cell.value)
            if val < 0:
                delta_min_cell.fill = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid")
            elif val < 11:
                delta_min_cell.fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
            else:
                delta_min_cell.fill = PatternFill(start_color="00FF00", end_color="00FF00", fill_type="solid")

        delta_max_cell = ws_margins.cell(row=row_num, column=delta_max_col)
        if delta_max_cell.value not in ['', None]:
            val = float(delta_max_cell.value)
            if val < 0:
                delta_max_cell.fill = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid")
            elif val < 11:
                delta_max_cell.fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
            else:
                delta_max_cell.fill = PatternFill(start_color="00FF00", end_color="00FF00", fill_type="solid")

for col_num in range(1, ws_margins.max_column + 1):
    column_letter = get_column_letter(col_num)
    max_length = 0
    for cell in ws_margins[column_letter]:
        try:
            if len(str(cell.value)) > max_length:
                max_length = len(str(cell.value))
        except:
            pass
    adjusted_width = min(max_length + 2, 50)
    ws_margins.column_dimensions[column_letter].width = adjusted_width

ws_margins.freeze_panes = 'D3'

# ============================================================================
# HEATER DUTY CYCLES SHEET
# ============================================================================
if PULL_HEATER_DATA and heater_results:
    ws_duty = wb.create_sheet("Heater Duty Cycles", 2)

    sorted_registers = sorted(all_heater_registers)

    row1_data = ['Heater']
    for case_name in sav_files:
        row1_data.append(os.path.basename(case_name))
    ws_duty.append(row1_data)

    row2_data = ['']
    for _ in sav_files:
        row2_data.append('Duty Cycle %')
    ws_duty.append(row2_data)

    for cell in ws_duty[1]:
        cell.font = Font(bold=True, size=11, color="FFFFFF")
        cell.fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        cell.alignment = Alignment(horizontal='center', vertical='center')

    for cell in ws_duty[2]:
        cell.font = Font(bold=True, size=10, color="FFFFFF")
        cell.fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        cell.alignment = Alignment(horizontal='center', vertical='center')

    for heater_name in sorted_registers:
        row_data = [heater_name]
        for sav in sav_files:
            case_name = os.path.basename(sav)
            reg_stats = heater_results.get(heater_name, {}).get(case_name)
            row_data.append(reg_stats['duty_cycle_pct'] if reg_stats else '')
        ws_duty.append(row_data)

        row_num = ws_duty.max_row
        for col_idx in range(2, 2 + len(sav_files)):
            cell = ws_duty.cell(row=row_num, column=col_idx)
            if cell.value not in ['', None]:
                if float(cell.value) > DUTY_CYCLE_WARNING_THRESHOLD:
                    cell.fill = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid")

    for col_num in range(1, ws_duty.max_column + 1):
        column_letter = get_column_letter(col_num)
        max_length = 0
        for cell in ws_duty[column_letter]:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        ws_duty.column_dimensions[column_letter].width = min(max_length + 2, 30)

    ws_duty.freeze_panes = 'B3'

# ============================================================================
# RAW DATA SHEET (ALL CASES IN ONE TAB)
# ============================================================================
ws_raw = wb.create_sheet("Raw Data", 3)

current_row = 1

for sav in sav_files:
    case_name = os.path.basename(sav)
    times = times_data[case_name]

    case_row = [case_name]
    ws_raw.append(case_row)
    case_cell = ws_raw.cell(row=current_row, column=1)
    case_cell.font = Font(bold=True, size=12, color="FFFFFF")
    case_cell.fill = PatternFill(start_color="FF6600", end_color="FF6600", fill_type="solid")
    case_cell.alignment = Alignment(horizontal='center', vertical='center')
    num_cols = 2 + len(times)
    ws_raw.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=num_cols)
    current_row += 1

    header_row = ['Submodel', 'Node'] + [round(t, 2) for t in times]
    ws_raw.append(header_row)
    for cell in ws_raw[current_row]:
        cell.font = Font(bold=True, size=10, color="FFFFFF")
        cell.fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        cell.alignment = Alignment(horizontal='center', vertical='center')
    current_row += 1

    for submodel in sorted_submodels:
        if case_name in raw_data and submodel in raw_data[case_name]:
            for node_name, temps in raw_data[case_name][submodel].items():
                row_data = [submodel, node_name] + [round(t, 2) if t is not None else '' for t in temps]
                ws_raw.append(row_data)
                current_row += 1

    ws_raw.append([])
    current_row += 1

for col_num in range(1, min(ws_raw.max_column + 1, 50)):
    column_letter = get_column_letter(col_num)
    max_length = 0
    for i, cell in enumerate(ws_raw[column_letter]):
        if i > 100:
            break
        try:
            if len(str(cell.value)) > max_length:
                max_length = len(str(cell.value))
        except:
            pass
    adjusted_width = min(max_length + 2, 30)
    ws_raw.column_dimensions[column_letter].width = adjusted_width

ws_raw.freeze_panes = 'C1'

# ============================================================================
# HEATER RAW DATA SHEET (OPTIONAL)
# ============================================================================
if PULL_HEATER_DATA and heater_data:
    ws_heater_raw = wb.create_sheet("Heater Raw Data", 4)

    current_row = 1
    for sav in sav_files:
        case_name = os.path.basename(sav)
        if case_name not in heater_data or not heater_data[case_name]:
            continue

        times = times_data[case_name]

        ws_heater_raw.append([case_name])
        case_cell = ws_heater_raw.cell(row=current_row, column=1)
        case_cell.font = Font(bold=True, size=12, color="FFFFFF")
        case_cell.fill = PatternFill(start_color="FF6600", end_color="FF6600", fill_type="solid")
        case_cell.alignment = Alignment(horizontal='center', vertical='center')
        num_cols = 1 + len(times)
        ws_heater_raw.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=num_cols)
        current_row += 1

        header_row = ['Heater (OT)'] + [round(t, 2) for t in times]
        ws_heater_raw.append(header_row)
        for cell in ws_heater_raw[current_row]:
            cell.font = Font(bold=True, size=10, color="FFFFFF")
            cell.fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
            cell.alignment = Alignment(horizontal='center', vertical='center')
        current_row += 1

        for heater_name in sorted(heater_data[case_name].keys()):
            values = heater_data[case_name][heater_name]
            row_data = [heater_name] + [round(v, 2) if v is not None else '' for v in values]
            ws_heater_raw.append(row_data)
            current_row += 1

        ws_heater_raw.append([])
        current_row += 1

    ws_heater_raw.freeze_panes = 'B1'

wb.save(excel_file)
print(f"Done. Results saved to: {excel_file}")
