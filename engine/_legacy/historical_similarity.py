import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from scipy.spatial.distance import euclidean
import matplotlib.pyplot as plt
import seaborn as sns

class HistoricalSimilarityAnalysis:
    """
    Find the 3 most similar historical teams for each current playoff team
    """
    
    def __init__(self, matchup_data_path, manager_stats_path, current_season=2025):
        """
        Parameters:
        -----------
        matchup_data_path : str
            Path to matchup_data.csv
        manager_stats_path : str
            Path to preach_manager_stats.csv
        current_season : int
            Current season year
        """
        self.matchup_data = pd.read_csv(matchup_data_path, encoding='latin-1')
        self.manager_stats = pd.read_csv(manager_stats_path, encoding='latin-1')
        self.current_season = current_season
        
    def get_playoff_elimination_round(self, manager, season):
        """
        Determine which playoff round a team was eliminated
        Returns the round number where they lost, or None if they won championship
        """
        # Special handling for 2020 - had 14 teams (4 rounds)
        if season == 2020:
            # 2020 structure: R1=Round of 14, R2=Quarters, R3=Semis, R4=Finals
            playoff_rounds_2020 = [
                ('Playoff Round 1', 1),  # Round of 14
                ('Playoff Round 2', 2),  # Quarterfinals
                ('Playoff Round 3', 3),  # Semifinals
                ('Playoff Round 4', 4)   # Finals
            ]
            
            for round_name, normalized_round in playoff_rounds_2020:
                round_game = self.matchup_data[
                    (self.matchup_data['Team_Name'] == manager) &
                    (self.matchup_data['Season_Year'] == season) &
                    (self.matchup_data['Week'] == round_name) &
                    (self.matchup_data['Is_Playoff'] == 'Yes') &
                    (self.matchup_data['Outcome'] == 'Loss')
                ]
                if len(round_game) > 0:
                    return normalized_round
        # Special handling for 2021 - had an extra wildcard round
        elif season == 2021:
            # 2021 structure: R1=Wildcard, R2=Quarters, R3=Semis, R4=Finals
            playoff_rounds_2021 = [
                ('Playoff Round 1', 1),  # Wildcard
                ('Playoff Round 2', 1),  # Actually Quarterfinals (normal R1)
                ('Playoff Round 3', 2),  # Actually Semifinals (normal R2)
                ('Playoff Round 4', 3)   # Finals (normal R3)
            ]
            
            for round_name, normalized_round in playoff_rounds_2021:
                round_game = self.matchup_data[
                    (self.matchup_data['Team_Name'] == manager) &
                    (self.matchup_data['Season_Year'] == season) &
                    (self.matchup_data['Week'] == round_name) &
                    (self.matchup_data['Is_Playoff'] == 'Yes') &
                    (self.matchup_data['Outcome'] == 'Loss')
                ]
                if len(round_game) > 0:
                    return normalized_round
        else:
            # Normal playoff structure (2022-2024)
            playoff_rounds = ['Playoff Round 1', 'Playoff Round 2', 'Playoff Round 3']
            for i, round_name in enumerate(playoff_rounds, start=1):
                round_game = self.matchup_data[
                    (self.matchup_data['Team_Name'] == manager) &
                    (self.matchup_data['Season_Year'] == season) &
                    (self.matchup_data['Week'] == round_name) &
                    (self.matchup_data['Is_Playoff'] == 'Yes') &
                    (self.matchup_data['Outcome'] == 'Loss')
                ]
                if len(round_game) > 0:
                    return i
        
        return None  # Won championship or no loss found
    
    def get_playoff_round1_performance(self, manager, season):
        """
        Get Round 1 playoff performance for a manager/team
        Special handling for 2021 wildcard format
        """
        # 2021 had a wildcard game - only Ethan Radecki and Cole Maney played Round 1
        if season == 2021:
            # Hard-coded 2021 wildcard game
            if manager == 'Ethan Radecki':
                return {
                    'played_round1': True,
                    'round1_outcome': 'Win',  # Won wildcard
                    'round1_score': 151.5
                }
            elif manager == 'Cole Maney':
                return {
                    'played_round1': True,
                    'round1_outcome': 'Loss',  # Lost wildcard
                    'round1_score': 135.68
                }
            else:
                # Other 2021 playoff teams had a bye, their "Round 1" was actually Round 2 (Quarterfinals)
                round2_game = self.matchup_data[
                    (self.matchup_data['Team_Name'] == manager) &
                    (self.matchup_data['Season_Year'] == season) &
                    (self.matchup_data['Week'] == 'Playoff Round 2') &
                    (self.matchup_data['Is_Playoff'] == 'Yes')
                ]
                
                if len(round2_game) > 0:
                    game = round2_game.iloc[0]
                    return {
                        'played_round1': True,
                        'round1_outcome': game['Outcome'],
                        'round1_score': game['Team_Score']
                    }
        
        # For all other seasons, look for Playoff Round 1
        round1_game = self.matchup_data[
            (self.matchup_data['Team_Name'] == manager) &
            (self.matchup_data['Season_Year'] == season) &
            (self.matchup_data['Week'] == 'Playoff Round 1') &
            (self.matchup_data['Is_Playoff'] == 'Yes')
        ]
        
        if len(round1_game) > 0:
            game = round1_game.iloc[0]
            return {
                'played_round1': True,
                'round1_outcome': game['Outcome'],
                'round1_score': game['Team_Score']
            }
        
        return {
            'played_round1': False,
            'round1_outcome': None,
            'round1_score': None
        }
    
    def calculate_late_season_performance(self, manager, season):
        """
        Calculate average points scored in weeks 10-13 for a manager/season
        """
        # Match on Team_Name (which is the manager name in matchup_data)
        late_season = self.matchup_data[
            (self.matchup_data['Team_Name'] == manager) &
            (self.matchup_data['Season_Year'] == season) &
            (self.matchup_data['Week'].isin(['Week 10', 'Week 11', 'Week 12', 'Week 13'])) &
            (self.matchup_data['Is_Playoff'] == 'No')
        ]
        
        if len(late_season) > 0:
            return late_season['Team_Score'].mean()
        return None
    
    def build_feature_dataset(self):
        """
        Build comprehensive feature dataset for all teams across all seasons
        """
        features_list = []
        
        for _, row in self.manager_stats.iterrows():
            team = row['Team']
            manager = row['Manager']  # This matches Team_Name in matchup_data
            season = row['Year']  # From manager_stats
            
            # Calculate late season performance using manager name
            late_season_ppg = self.calculate_late_season_performance(manager, season)
            
            # Skip if we don't have late season data
            if late_season_ppg is None:
                continue
            
            # Get playoff Round 1 performance using manager name
            playoff_round1 = self.get_playoff_round1_performance(manager, season)
            
            # Get elimination round
            elimination_round = self.get_playoff_elimination_round(manager, season)
            
            features = {
                'Team': team,
                'Year': season,
                'Manager': manager,
                'Win%': row['W%'],
                'PF/G': row['PF/G'],
                'PA/G': row['PA/G'],
                'Late_Season_PF/G': late_season_ppg,
                'LR_zscore': row['LR_zscore'],
                'Dominance_Score': row['Dominance_Score'],
                'Point_Differential': row['DIFF'],
                'Playoffs': row['Playoffs'],
                'Champ_App': row['Champ_App'],
                'Champ_W': row['Champ_W'],
                'Draft_Slot': row['Draft_Slot'],
                'Placement': row['Placement_within_Year'],
                'Round1_Played': playoff_round1['played_round1'],
                'Round1_Outcome': playoff_round1['round1_outcome'],
                'Round1_Score': playoff_round1['round1_score'],
                'Elimination_Round': elimination_round
            }
            
            features_list.append(features)
        
        features_df = pd.DataFrame(features_list)
        return features_df
    
    def find_similar_teams(self, current_team_features, historical_features, 
                          feature_weights=None, n_matches=3):
        """
        Find n most similar historical teams using weighted Euclidean distance
        
        Parameters:
        -----------
        current_team_features : dict
            Feature values for current team
        historical_features : pd.DataFrame
            Historical team features
        feature_weights : dict
            Weights for each feature (higher = more important)
        n_matches : int
            Number of similar teams to return
        """
        if feature_weights is None:
            # Weights based on your priorities:
            # 1. Late Season PF/G (most important)
            # 2. PF/G
            # 3. Win%
            # 4. Luck (LR_zscore)
            # 5. Dominance
            # 6. Draft Slot
            # 7. Point Differential (least important)
            feature_weights = {
                'Late_Season_PF/G': 2.0,  # Most important
                'PF/G': 1.7,
                'Win%': 1.4,
                'LR_zscore': 1.1,
                'Dominance_Score': 0.9,
                'Draft_Slot': 0.6,
                'Point_Differential': 0.4  # Least important
            }
        
        # Features to use for similarity calculation
        comparison_features = list(feature_weights.keys())
        
        # Prepare data for scaling
        all_data = historical_features[comparison_features].copy()
        current_data = pd.DataFrame([current_team_features])[comparison_features]
        
        # Standardize features
        scaler = StandardScaler()
        all_data_scaled = scaler.fit_transform(all_data)
        current_data_scaled = scaler.transform(current_data)
        
        # Apply weights
        weights_array = np.array([feature_weights[f] for f in comparison_features])
        all_data_weighted = all_data_scaled * weights_array
        current_data_weighted = current_data_scaled * weights_array
        
        # Calculate distances
        distances = []
        for idx, historical_vector in enumerate(all_data_weighted):
            dist = euclidean(current_data_weighted[0], historical_vector)
            distances.append({
                'index': idx,
                'distance': dist
            })
        
        # Sort by distance and get top n
        distances_df = pd.DataFrame(distances).sort_values('distance')
        top_matches_idx = distances_df.head(n_matches)['index'].values
        
        # Get the matched teams
        similar_teams = historical_features.iloc[top_matches_idx].copy()
        similar_teams['similarity_distance'] = distances_df.head(n_matches)['distance'].values
        
        # Calculate similarity score (inverse of distance, normalized to 0-100)
        max_dist = distances_df['distance'].max()
        similar_teams['similarity_score'] = (
            (1 - (similar_teams['similarity_distance'] / max_dist)) * 100
        )
        
        return similar_teams
    
    def analyze_playoff_teams(self, playoff_teams, feature_weights=None):
        """
        Analyze all playoff teams and find their historical comparisons
        
        Parameters:
        -----------
        playoff_teams : list
            List of team names that made playoffs this year
        feature_weights : dict
            Optional custom weights for features
        
        Returns:
        --------
        results : dict
            Dictionary with team names as keys and similar teams as values
        """
        # Build feature dataset
        all_features = self.build_feature_dataset()
        
        # Separate current season from historical
        current_season_features = all_features[
            all_features['Year'] == self.current_season
        ]
        historical_features = all_features[
            all_features['Year'] < self.current_season
        ]
        
        results = {}
        
        for team in playoff_teams:
            # playoff_teams contains manager names, find their current team name
            team_data = current_season_features[
                current_season_features['Manager'] == team
            ]
            
            if len(team_data) == 0:
                print(f"Warning: No data found for {team} in {self.current_season}")
                continue
            
            team_features = team_data.iloc[0].to_dict()
            
            similar_teams = self.find_similar_teams(
                team_features,
                historical_features,
                feature_weights=feature_weights,
                n_matches=3
            )
            
            results[team] = {
                'current_features': team_features,
                'similar_teams': similar_teams
            }
        
        return results
    
    def print_results(self, results):
        """
        Print formatted results for each playoff team
        """
        print("=" * 80)
        print("HISTORICAL TEAM SIMILARITY ANALYSIS")
        print("Finding the 3 Most Similar Teams from League History")
        print("=" * 80)
        
        for team, data in results.items():
            print(f"\n{'='*80}")
            print(f"🏈 {team.upper()}")
            print(f"   Manager: {data['current_features']['Manager']}")
            print(f"{'='*80}")
            
            print(f"\n2024 SEASON STATISTICS:")
            print(f"  Win%: {data['current_features']['Win%']:.3f}")
            print(f"  PF/G: {data['current_features']['PF/G']:.2f}")
            print(f"  PA/G: {data['current_features']['PA/G']:.2f}")
            print(f"  Late Season PF/G (Wks 10-13): {data['current_features']['Late_Season_PF/G']:.2f}")
            print(f"  LR Z-Score: {data['current_features']['LR_zscore']:.2f}")
            print(f"  Dominance Score: {data['current_features']['Dominance_Score']:.2f}")
            
            print(f"\n📊 TOP 3 MOST SIMILAR HISTORICAL TEAMS:")
            print("-" * 80)
            
            for idx, (_, similar_team) in enumerate(data['similar_teams'].iterrows(), 1):
                print(f"\n  #{idx} - {similar_team['Team']} ({int(similar_team['Year'])}) - {similar_team['Manager']}")
                print(f"      Similarity Score: {similar_team['similarity_score']:.1f}/100")
                print(f"      Win%: {similar_team['Win%']:.3f} | PF/G: {similar_team['PF/G']:.2f} | PA/G: {similar_team['PA/G']:.2f}")
                print(f"      Late Season PF/G: {similar_team['Late_Season_PF/G']:.2f}")
                print(f"      Season Result: {self._format_result(similar_team)}")
                
                # Show playoff performance
                if similar_team['Playoffs'] == 1:
                    print(f"      Made Playoffs: Yes")
                    
                    # Show elimination round
                    if pd.notna(similar_team['Elimination_Round']):
                        elim_round = int(similar_team['Elimination_Round'])
                        year = int(similar_team['Year'])
                        
                        # Different naming for 2020 (14 teams)
                        if year == 2020:
                            round_names = {1: 'Round of 14', 2: 'Quarterfinals', 3: 'Semifinals', 4: 'Finals'}
                        else:
                            round_names = {1: 'Round 1', 2: 'Semifinals', 3: 'Finals'}
                        
                        round_name = round_names.get(elim_round, f'Round {elim_round}')
                        print(f"      Eliminated in: {round_name}")
                    
                    if similar_team['Round1_Played']:
                        outcome = "Won" if similar_team['Round1_Outcome'] == 'Win' else "Lost"
                        print(f"      Round 1: {outcome} ({similar_team['Round1_Score']:.1f} pts)")
                else:
                    print(f"      Made Playoffs: No")
    
    def _format_result(self, team_row):
        """Helper to format season result"""
        if team_row['Champ_W'] == 1:
            return "🏆 CHAMPION"
        elif team_row['Champ_App'] == 1:
            return "🥈 Runner-Up"
        elif team_row['Playoffs'] == 1:
            return f"Made Playoffs (Finished {int(team_row['Placement'])})"
        else:
            return f"Missed Playoffs (Finished {int(team_row['Placement'])})"
    
    def create_comparison_visual(self, results, output_path=None):
        """
        Create clean visual comparison cards for each playoff team
        Generates individual PNG files for each team
        """
        all_figures = []
        
        for manager_name, data in results.items():
            # Create individual figure for each team
            fig = plt.figure(figsize=(10, 9))
            ax = plt.subplot(1, 1, 1)
            ax.axis('off')
            
            # Get current team info
            team_name = data['current_features']['Team']
            current = data['current_features']
            similar = data['similar_teams']
            
            # Background color
            ax.add_patch(plt.Rectangle((0, 0), 1, 1, facecolor='#f5f5f5', transform=ax.transAxes, zorder=0))
            
            # Title section
            ax.text(0.5, 0.95, team_name, transform=ax.transAxes, 
                   fontsize=22, fontweight='bold', ha='center', va='top',
                   color='#6c5a6c')
            ax.text(0.5, 0.89, f'{manager_name} - 2025 Season', transform=ax.transAxes,
                   fontsize=14, ha='center', va='top', color='#555555', style='italic')
            
            # Current season stats box
            stats_text = f"Win%: {current['Win%']:.3f}  |  PF/G: {current['PF/G']:.1f}  |  Late Season PF/G: {current['Late_Season_PF/G']:.1f}"
            ax.text(0.5, 0.82, stats_text, transform=ax.transAxes,
                   fontsize=12, ha='center', va='top', 
                   bbox=dict(boxstyle='round,pad=0.6', facecolor='white', edgecolor='#9c949c', linewidth=2))
            
            # Historical comparisons section
            ax.text(0.5, 0.74, 'Most Similar Historical Teams', transform=ax.transAxes,
                   fontsize=15, fontweight='bold', ha='center', va='top', color='#333333')
            
            # Draw each historical match - adjusted positions for better spacing
            y_positions = [0.65, 0.44, 0.23]
            colors = ['#6c5a6c', '#8a93ab', '#9c949c']
            
            for i, (_, sim_team) in enumerate(similar.iterrows()):
                y_start = y_positions[i]
                
                # Card background
                rect = plt.Rectangle((0.05, y_start - 0.20), 0.9, 0.19, 
                                    facecolor='white', edgecolor=colors[i], 
                                    linewidth=3, transform=ax.transAxes, zorder=1)
                ax.add_patch(rect)
                
                # Rank badge
                rank_circle = plt.Circle((0.09, y_start - 0.105), 0.03, 
                                        facecolor=colors[i], transform=ax.transAxes, zorder=2)
                ax.add_patch(rank_circle)
                ax.text(0.09, y_start - 0.105, f'#{i+1}', transform=ax.transAxes,
                       fontsize=14, fontweight='bold', ha='center', va='center', 
                       color='white', zorder=3)
                
                # Team name and year
                ax.text(0.15, y_start - 0.04, sim_team['Team'], transform=ax.transAxes,
                       fontsize=13, fontweight='bold', ha='left', va='top', color='#333333')
                ax.text(0.15, y_start - 0.08, f"({int(sim_team['Year'])}) - {sim_team['Manager']}", 
                       transform=ax.transAxes, fontsize=10, ha='left', va='top', 
                       color='#666666', style='italic')
                
                # Similarity score
                ax.text(0.91, y_start - 0.04, f"{sim_team['similarity_score']:.0f}%", 
                       transform=ax.transAxes, fontsize=16, fontweight='bold', 
                       ha='right', va='top', color=colors[i])
                ax.text(0.91, y_start - 0.08, 'Match', transform=ax.transAxes,
                       fontsize=9, ha='right', va='top', color='#666666')
                
                # Stats row
                stats_str = f"W%: {sim_team['Win%']:.3f}  |  PF/G: {sim_team['PF/G']:.1f}  |  Late: {sim_team['Late_Season_PF/G']:.1f}"
                ax.text(0.15, y_start - 0.12, stats_str, transform=ax.transAxes,
                       fontsize=10, ha='left', va='top', color='#444444',
                       family='monospace')
                
                # Outcome
                result_icon = ""
                result_color = '#333333'
                
                if sim_team['Champ_W'] == 1:
                    result_icon = "★ CHAMPION"
                    result_color = '#d4af37'
                elif sim_team['Champ_App'] == 1:
                    result_icon = "◆ Runner-Up"
                    result_color = '#c0c0c0'
                elif sim_team['Playoffs'] == 1:
                    # Show elimination round if available
                    has_elim_round = 'Elimination_Round' in sim_team and pd.notna(sim_team['Elimination_Round'])
                    
                    if has_elim_round:
                        elim_round = int(sim_team['Elimination_Round'])
                        year = int(sim_team['Year'])
                        
                        # Different naming for 2020 (14 teams)
                        if year == 2020:
                            round_names = {1: 'Round of 14', 2: 'Quarterfinals', 3: 'Semifinals', 4: 'Finals'}
                        else:
                            round_names = {1: 'Quarterfinals', 2: 'Semifinals', 3: 'Finals'}
                        
                        round_name = round_names.get(elim_round, f'R{elim_round}')
                        
                        # Show score if it was Round 1
                        if sim_team['Round1_Played'] and elim_round == 1:
                            result_icon = f"✗ Lost in {round_name} ({sim_team['Round1_Score']:.0f} pts)"
                        else:
                            result_icon = f"✗ Lost in {round_name}"
                        result_color = '#d9534f'
                    elif sim_team['Round1_Played']:
                        # Fallback to Round 1 info if no elimination round data
                        if sim_team['Round1_Outcome'] == 'Win':
                            result_icon = f"✓ Won Quarterfinals ({sim_team['Round1_Score']:.0f} pts)"
                            result_color = '#2d8659'
                        else:
                            result_icon = f"✗ Lost in Quarterfinals ({sim_team['Round1_Score']:.0f} pts)"
                            result_color = '#d9534f'
                    else:
                        result_icon = "Made Playoffs"
                        result_color = '#666666'
                else:
                    result_icon = "Missed Playoffs"
                    result_color = '#999999'
                
                ax.text(0.15, y_start - 0.17, result_icon, transform=ax.transAxes,
                       fontsize=11, ha='left', va='top', color=result_color, fontweight='bold')
            
            plt.tight_layout(pad=2.0)
            
            # Save individual file
            if output_path:
                # Create filename based on manager name (cleaned for filesystem)
                clean_name = manager_name.replace(' ', '_').replace('.', '')
                individual_path = output_path.replace('.png', f'_{clean_name}.png')
                plt.savefig(individual_path, dpi=300, bbox_inches='tight', pad_inches=0.3, facecolor='white')
                print(f"✅ Saved: {individual_path}")
            
            all_figures.append(fig)
            plt.close(fig)
        
        print(f"\n✅ Generated {len(all_figures)} individual team comparison images")
        return all_figures
    
    def export_to_csv(self, results, output_path='historical_similarities.csv'):
        """
        Export results to CSV for easy reference
        """
        export_data = []
        
        for team, data in results.items():
            current = data['current_features']
            
            for rank, (_, similar_team) in enumerate(data['similar_teams'].iterrows(), 1):
                export_data.append({
                    '2025_Team': team,
                    '2025_Manager': current['Manager'],
                    '2025_Win%': current['Win%'],
                    '2025_PF/G': current['PF/G'],
                    '2025_PA/G': current['PA/G'],
                    '2025_Late_Season_PF/G': current['Late_Season_PF/G'],
                    'Similarity_Rank': rank,
                    'Historical_Team': similar_team['Team'],
                    'Historical_Season': int(similar_team['Year']),
                    'Historical_Manager': similar_team['Manager'],
                    'Historical_Win%': similar_team['Win%'],
                    'Historical_PF/G': similar_team['PF/G'],
                    'Historical_PA/G': similar_team['PA/G'],
                    'Historical_Late_Season_PF/G': similar_team['Late_Season_PF/G'],
                    'Historical_Result': self._format_result(similar_team),
                    'Historical_Made_Playoffs': 'Yes' if similar_team['Playoffs'] == 1 else 'No',
                    'Historical_Elimination_Round': int(similar_team['Elimination_Round']) if pd.notna(similar_team.get('Elimination_Round')) else None,
                    'Historical_Round1_Outcome': similar_team['Round1_Outcome'] if similar_team['Round1_Played'] else 'N/A',
                    'Historical_Round1_Score': similar_team['Round1_Score'] if similar_team['Round1_Played'] else None,
                    'Similarity_Score': similar_team['similarity_score']
                })
        
        export_df = pd.DataFrame(export_data)
        export_df.to_csv(output_path, index=False)
        print(f"\n✅ Results exported to {output_path}")
        
        return export_df


# Example usage
if __name__ == "__main__":
    # Initialize analyzer
    analyzer = HistoricalSimilarityAnalysis(
        matchup_data_path='static/data/matchup_data.csv',
        manager_stats_path='static/data/preach_manager_stats.csv',
        current_season=2025
    )
    
    # 2025 Playoff teams in seed order
    playoff_teams_2025 = [
        'Ben Castaldo',      # Seed 1
        'Cole Maney',        # Seed 2
        'Ryan P McQuaid',    # Seed 3 (no period)
        'Baylen Slansky',    # Seed 4
        'Carmine Pittelli Jr.',  # Seed 5
        'Ethan Radecki',     # Seed 6
        'Anthony Kelly',     # Seed 7
        'Charlie Gorman'     # Seed 8
    ]
    
    # Feature weights (customized to your priorities)
    custom_weights = {
        'Late_Season_PF/G': 2.0,    # Most important
        'PF/G': 1.7,
        'Win%': 1.4,
        'LR_zscore': 1.1,
        'Dominance_Score': 0.9,
        'Draft_Slot': 0.6,
        'Point_Differential': 0.4   # Least important
    }
    
    # Run analysis
    results = analyzer.analyze_playoff_teams(
        playoff_teams_2025,
        feature_weights=custom_weights
    )
    
    # Print results
    analyzer.print_results(results)
    
    # Create visualizations (individual files for each team)
    figs = analyzer.create_comparison_visual(
        results,
        output_path='playoff_historical_comparisons.png'
    )
    
    # Export to CSV
    analyzer.export_to_csv(results)