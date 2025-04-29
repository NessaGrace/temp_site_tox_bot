import os
import time
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from dotenv import load_dotenv

# --- Configuration & Constants ---
load_dotenv()

# --- Credentials & API Setup ---
try:
    GEMINI_API_KEY = os.environ["GOOGLE_API_KEY"]
    SERVICE_ACCOUNT_FILE = os.environ["SERVICE_ACCOUNT_FILE"]
    GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

    # Scopes define the access level
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    # Authenticate Google Sheets
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(GOOGLE_SHEET_ID)
    bids_worksheet = sheet.worksheet("Site Toxicity Assessment Bid Form Responses") # Adjust sheet name if needed
    leaderboard_worksheet = sheet.worksheet("Leaderboard") # Adjust sheet name

    # Configure Gemini
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash-latest') # Or 'gemini-pro' if more power needed

except KeyError as e:
    print(f"ERROR: Environment variable not set: {e}")
    exit()
except Exception as e:
        print(f"ERROR setting up APIs: {e}")
        exit()


# --- Case Site Data (Now with full paragraph descriptions) ---
case_sites = {
    "Site 1": "Site 1: The Rocky Flats Plant was established in 1952 as part of the nuclear weapons complex to manufacture nuclear weapons components under the jurisdiction and control of DOE and its predecessor agencies. Manufacturing activities, accidental industrial fires, spills, and support activities resulted in the release of hazardous constituents to air, soil, sediment, groundwater, and surface water at the Rocky Flats Plant. Contaminants released to the environment include the radionuclides plutonium, americium, and uranium isotopes; organic solvents including trichloroethene, tetrachloroethene, and carbon tetrachloride; metals such as chromium; and nitrates. Groundwater and landfills are of concern.",
    "Site 2": "Site 2: The Rocky Mountain Arsenal (RMA) is nearly 27 square miles, roughly the size of Manhattan. RMA is located at the western edge of the Colorado plains, near the foothills of the Rocky Mountains, ten miles northeast of downtown Denver, Colorado. The U.S. Army established the RMA in 1942 to produce incendiary munitions and chemical warfare agents such as mustard gas used in World War II. Following the war, and through the early 1980s, the Army continued to use these facilities. Private industry was also encouraged to lease facilities at RMA after the war to foster economic growth in the area, offset operational costs and maintain facilities for national security. Under the lease program, Julius Hyman and Company began producing pesticides in 1946. In 1952, Shell Chemical Company acquired Julius Hyman and Company and continued to produce agricultural pesticides onsite until 1982. These activities over time resulted in widespread and significant environmental contamination across the site. The primary contaminants include organochloride pesticides, organophosphate pesticides, carbamate insecticides, organic solvents and feedstock chemicals used as raw products or intermediates in the manufacturing process (e.g., chlorinated benzenes), heavy metals, chemical warfare material and their related breakdown products and biological warfare agent such as TX. Additionally, ordnance (including incendiary munitions) was manufactured and tested, and asbestos and polychlorinated biphenyls (PCBs) were used at RMA. Today, it is considered a hazardous waste site according to the Colorado Department of Public and Environmental Health. Groundwater is of particular concern.",
    "Site 3": "Site 3: The 160-acre Marshall Landfill site consists of two adjacent 80-acre landfills. The northern landfill is Marshall Landfill, and the southern landfill is Boulder Landfill. Marshall Landfill began operating in 1965 as a solid waste composting and disposal operation. Between 1969 and 1974, Marshall Landfill accepted municipal waste, unstabilized sewage sludge, and many unknown, potentially hazardous, wastes. In 1974, Boulder County discontinued use of Marshall Landfill when Boulder Landfill opened to the immediate south. Boulder Landfill closed in January 1992. Sources of contamination include areas of saturated refuse, waste disposal trenches, small areas where organic solvents were disposed and two unlined leachate lagoons. Landfill operations contaminated surface water and on-site shallow groundwater. Main compounds of concern: Volatile organic compounds (VOCs), such as benzene, trichloroethylene (TCE) and tetrachloroethylene (PCE). Heavy metals, such as barium, iron, manganese and zinc. Major ions, such as chloride, nitrate and sulfate",
    "Site 4": "Site 4: The Air Force Plant Peter J. Kiewit and Sons (PJKS) site is owned and operated by Lockheed Martin Astronautics Operation. The plant is located 25 miles southwest of Denver, near Waterton Canyon, Colorado. PJKS consists of 464 acres, and is surrounded by another 4,700 acres of Lockheed Martin land. Company operations at PJKS include testing Titan rockets, as well as designing, developing, testing and manufacturing advanced technical systems for space and defense. Historical operations contaminated soil and groundwater with hazardous chemicals. Following cleanup, operation and maintenance activities are ongoing. Main contaminants of concern : TCE and NDMA in groundwater.",
    "Site 5": "Solve algal blooms microbially.",
    "Site 6": "The Alma WWTF wants to meet its ammonia discharge permits."
}

# --- Helper Functions ---
def get_pending_bids_data():
    """Fetches rows where 'Gemini Feedback' is empty and includes their row index."""
    all_data = bids_worksheet.get_all_records()
    df = pd.DataFrame(all_data)
    if 'Gemini Feedback' not in df.columns or 'Case Site Bidding On' not in df.columns:
        print("ERROR: Missing 'Gemini Feedback' or 'Case Site Bidding On' column in the sheet.")
        return pd.DataFrame()

    df['SheetRowIndex'] = df.index + 2
    pending_df = df[df['Gemini Feedback'].isnull() | (df['Gemini Feedback'] == '')].copy()
    return pending_df

def evaluate_reasoning(team_name, specialty, reasoning, case_name):
    """Asks Gemini to evaluate a single bid's reasoning based on the case description from the script."""
    if case_name not in case_sites:
        print(f"WARNING: Case details for '{case_name}' not found in script.")
        return {"quality": "Error", "feedback": "Case details not found in script."}

    case_description = case_sites[case_name]
    specialty_options = ["aerobic", "anaerobic", "photosynthetic", "heterotrophic"]

    prompt = f"""You are an environmental microbiology expert evaluating a remediation bid proposal.
    Site Details: {case_description}
    Bidding Team's Specialty: {specialty}
    Team's Reasoning Provided: "{reasoning}"
    The microbial specialty must be one of the following: {', '.join(specialty_options)}.
    Participants can describe how their chosen specialty will be modified or who they could partner with for a different specialty, but they must choose one of the four.

    Based *only* on the reasoning provided, evaluate if the proposed approach using {specialty} microbes is technically sound for remediating the contamination described in the 'Site Details'.
    Provide a brief (1-2 sentence) explanation for your evaluation.
    Conclude your entire response *strictly* with one of the following on a new line:
    Bid Quality: Highly competitive
    Bid Quality: Eligible
    Bid Quality: Unfunded
    """
    try:
        response = model.generate_content(prompt)
        time.sleep(1) # Avoid hitting rate limits
        # --- Basic Parsing (Improve with Regex for robustness) ---
        text = response.text.strip()
        quality = "Error"
        feedback = text
        if text.endswith("Bid Quality: Highly competitive"):
            quality = "Highly competitive"
            feedback = text.replace("Bid Quality: Highly competitive", "").strip()
        elif text.endswith("Bid Quality: Eligible"):
            quality = "Eligible"
            feedback = text.replace("Bid Quality: Eligible", "").strip()
        elif text.endswith("Bid Quality: Unfunded"):
            quality = "Unfunded"
            feedback = text.replace("Bid Quality: Unfunded", "").strip()
        else:
            feedback = f"Parsing Error: Unexpected LLM response format.\n{text}" # Log unexpected format
        # --- End Basic Parsing ---

        print(f"  Evaluation for {team_name} ({specialty}): {quality}")
        return {"quality": quality, "feedback": feedback}

    except Exception as e:
        print(f"ERROR evaluating bid for {team_name}: {e}")
        return {"quality": "Error", "feedback": str(e)}

def compare_and_select_winner(highly_competitive_bids, eligible_bids, case_name):
    """Asks Gemini to compare 'Highly competitive' and 'Eligible' bids and select the best based on the case description from the script."""
    if case_name not in case_sites:
        print(f"WARNING: Case details for '{case_name}' not found in script for comparison.")
        return None

    case_description = case_sites[case_name]
    all_bids_to_compare = highly_competitive_bids + eligible_bids # Combine highly competitive and eligible bids

    if not all_bids_to_compare:
        return None # No bids to compare
    if len(all_bids_to_compare) == 1:
        return all_bids_to_compare[0]['SheetRowIndex'] # The only bid wins

    proposals_text = ""
    bid_map = {} # Map proposal number back to SheetRowIndex

    for i, bid in enumerate(all_bids_to_compare):
        proposal_num = i + 1
        proposals_text += f"Proposal {proposal_num}:\n"
        proposals_text += f"  Team: {bid['Team Name']}\n"
        proposals_text += f"  Specialty: {bid['Microbial Specialty']}\n"
        proposals_text += f"  Reasoning: \"{bid['Reasoning for Bid']}\"\n\n"
        bid_map[proposal_num] = bid['SheetRowIndex']

    prompt = f"""You are an environmental microbiology expert selecting the single best proposal to remediate the following site: {case_description}. The following proposals have been deemed either technically sound or potentially viable based on their reasoning.
    The microbial specialty used must be one of the following: aerobic, anaerobic, photosynthetic, or heterotrophic. Participants can describe how their chosen specialty will be modified or who they could partner with for a different specialty, but they must choose one of the four.

    Compare these proposals based *only* on the convincingness, clarity, and potential efficiency implied by their reasoning. Which proposal presents the strongest overall case for this specific site?

    {proposals_text}
    Provide a brief (1 sentence) rationale for your choice.
    Conclude your entire response *strictly* with the winning proposal number on a new line, like this:
    Winning Proposal: [Number]
    """
    try:
        response = model.generate_content(prompt)
        time.sleep(1) # Avoid hitting rate limits
        # --- Basic Parsing ---
        text = response.text.strip()
        winner_line = text.splitlines()[-1]
        if "Winning Proposal:" in winner_line:
            try:
                winner_num_str = winner_line.split(":")[-1].strip()
                winner_num = int(winner_num_str)
                if winner_num in bid_map:
                    winning_row_index = bid_map[winner_num]
                    print(f"  Comparison Winner: Proposal {winner_num} (Row {winning_row_index})")
                    return winning_row_index # Return the SheetRowIndex
                else:
                    print(f"ERROR: Gemini specified winning proposal number {winner_num}, which is invalid.")
                    return None # Invalid number returned
            except ValueError:
                print(f"ERROR: Could not parse winner number from '{winner_line}'")
                return None # Parsing error
        else:
            print(f"ERROR: Could not find 'Winning Proposal:' line in comparison response.\n{text}")
            return None # Format error
        # --- End Basic Parsing ---

    except Exception as e:
        print(f"ERROR comparing bids: {e}")
        return None

def update_sheet_row(row_index, status, feedback, quality, is_winner, points):
    """Updates a specific row in the Google Sheet."""
    try:
        headers = bids_worksheet.row_values(1)
        status_col = headers.index('Evaluation Status') + 1
        feedback_col = headers.index('Gemini Feedback') + 1
        quality_col = headers.index('Bid Quality') + 1
        winner_col = headers.index('Is Winning Bid') + 1
        points_col = headers.index('Points Awarded') + 1

        cell_updates = [
            gspread.Cell(row_index, status_col, status),
            gspread.Cell(row_index, feedback_col, feedback),
            gspread.Cell(row_index, quality_col, quality), # Keep original quality
            gspread.Cell(row_index, winner_col, "Yes" if is_winner else "No"),
            gspread.Cell(row_index, points_col, points)
        ]
        bids_worksheet.update_cells(cell_updates, value_input_option='USER_ENTERED')
        print(f"  Updated Row {row_index}: Status='{status}', Quality='{quality}', Winner='{is_winner}', Points='{points}'")
        time.sleep(0.5)
    except ValueError as e:
        print(f"ERROR updating row {row_index}: Column not found? {e}. Headers: {headers}")
    except Exception as e:
        print(f"ERROR updating row {row_index} in sheet: {e}")


def update_leaderboard():
    """Recalculates and updates the leaderboard sheet."""
    try:
        print("Updating leaderboard...")
        all_data = bids_worksheet.get_all_records()
        if not all_data:
            print("No bid data found to update leaderboard.")
            return

        df = pd.DataFrame(all_data)
        if 'Team Name' not in df.columns or 'Points Awarded' not in df.columns:
            print("ERROR: Missing 'Team Name' or 'Points Awarded' column for leaderboard calculation.")
            return

        df['Points Awarded'] = pd.to_numeric(df['Points Awarded'], errors='coerce').fillna(0).astype(int)

        leaderboard_data = df.groupby('Team Name')['Points Awarded'].sum().reset_index()
        leaderboard_data = leaderboard_data.sort_values(by='Points Awarded', ascending=False)

        leaderboard_worksheet.clear() # Clears the entire sheet! Use with caution or clear specific range.

        # Write header
        leaderboard_worksheet.update('A1', [['Team Name', 'Total Points']], value_input_option='USER_ENTERED')

        # Write new data
        if not leaderboard_data.empty:
            leaderboard_worksheet.update('A2', leaderboard_data.values.tolist(), value_input_option='USER_ENTERED')
        print("Leaderboard updated.")

    except Exception as e:
        print(f"ERROR updating leaderboard: {e}")


# --- Main Processing Logic ---

print("Starting Bioremediation Bid Evaluation Process...")
pending_bids = get_pending_bids_data()

if pending_bids.empty:
    print("No pending bids to process.")
else:
    print(f"Found {len(pending_bids)} pending bids.")
    # Group bids by the case site they are for
    grouped = pending_bids.groupby('Case Site Bidding On') # Ensure this column name matches your form/sheet

    for case_name, bids_for_case_df in grouped:
        print(f"\n--- Processing Case: {case_name} ---")
        if case_name not in case_sites:
            print(f"WARNING: Details for case '{case_name}' not found in script config. Skipping.")
            # Mark these rows as error/skipped in the sheet
            for index, row_data in bids_for_case_df.iterrows():
                update_sheet_row(row_data['SheetRowIndex'], "Skipped", "Case details missing", "Error", False, 0)
            continue

        case_description = case_sites[case_name]
        print(f"  Case Description: {case_description}")

        highly_competitive_bids_list = [] # Store dicts of bids rated 'Highly competitive'
        eligible_bids_list = [] # Store dicts of bids rated 'Eligible'
        processed_rows = [] # Keep track of rows processed in this batch for this case

        # 1. Evaluate each bid individually
        for index, row_data in bids_for_case_df.iterrows():
            sheet_row_idx = row_data['SheetRowIndex']
            processed_rows.append(sheet_row_idx)
            print(f"  Evaluating Bid - Row: {sheet_row_idx}, Team: {row_data['Team Name']}")

            eval_result = evaluate_reasoning(
                row_data['Team Name'],
                row_data['Microbial Specialty'], # Adjust column name if needed
                row_data['Reasoning for Bid'], # Adjust column name if needed
                case_name # Pass the case name to retrieve description
            )

            # Store bids based on their evaluation
            if eval_result["quality"] == "Highly competitive":
                highly_competitive_bids_list.append(row_data.to_dict())
            elif eval_result["quality"] == "Eligible":
                eligible_bids_list.append(row_data.to_dict())

            # Update the sheet immediately with individual evaluation result (but not winner status yet)
            update_sheet_row(sheet_row_idx, "Evaluated", eval_result["feedback"], eval_result["quality"], False, 0)

        # 2. Compare 'Highly competitive' and 'Eligible' bids and select winner for this case
        winning_row_index = None
        if highly_competitive_bids_list or eligible_bids_list: #check if either list has bids
            print(f"  Comparing bids for {case_name}...")
            winning_row_index = compare_and_select_winner(highly_competitive_bids_list, eligible_bids_list, case_name) # Pass both lists

            if winning_row_index:
                print(f"   Winner for {case_name} determined: Row {winning_row_index}")
                # Update the winning row specifically
                #  The quality should come from the original evaluation
                winning_bid = next((bid for bid in highly_competitive_bids_list + eligible_bids_list if bid['SheetRowIndex'] == winning_row_index), None)
                if winning_bid:
                    original_quality = winning_bid.get('Bid Quality')
                    update_sheet_row(winning_row_index, "Evaluated", "Selected as Best Bid", original_quality, True, 1)
                else:
                    print(f"ERROR: Could not find winning bid in evaluated bids.")
                    update_sheet_row(winning_row_index, "Evaluated", "Selected as Best Bid", "Error", True, 1) # set to error, so we can debug
            else:
                print(f"  No single winner determined for {case_name}.")
                #  No points awarded if no winner selected from comparison
        else:
            print(f"  No 'Highly competitive' or 'Eligible' quality bids submitted for {case_name}.")

        # 3. Award points.  Only the winner gets points.

# --- Final Step ---
update_leaderboard()

print("\nBid Evaluation Process Finished.")
