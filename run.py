# Logging
import os
import wandb
from tensorboardX import SummaryWriter

# Config system
import hydra
from omegaconf import OmegaConf, DictConfig

# Utils
from tqdm import tqdm
import datetime
from time import time, sleep
from typing import Dict, Type
import cProfile

# ML libraries
import numpy as np
from jax import random

# Project imports
from src.environment import env_name_to_EnvClass
from src.agents import agent_name_to_AgentSpeciesClass
from src.models import model_name_to_ModelClass
from src.video import VideoWriter
from src.time_measure import RuntimeMeter
from src.utils import try_get_seed


@hydra.main(config_path="configs", config_name="default.yaml")
def main(config: DictConfig):
    print("Configuration used :")
    print(OmegaConf.to_yaml(config))
    config = OmegaConf.to_container(config, resolve=True)

    # ================ Configuration ================

    # Hyperparameters
    n_timesteps: int = config["n_timesteps"]

    # Logging
    do_wandb: bool = config["do_wandb"]
    do_tb: bool = config["do_tb"]
    do_cli: bool = config["do_cli"]
    do_tqdm: bool = config["do_tqdm"]
    do_snakeviz: bool = config["do_snakeviz"]
    config_dirs_to_log: Dict[str, bool] = config["config_dirs_to_log"]

    # Video recording
    do_video: bool = config["do_video"]
    n_steps_between_videos: int = config["n_steps_between_videos"]
    n_steps_per_video: int = config["n_steps_per_video"]
    n_steps_between_frames: int = config["n_steps_between_frames"]
    assert (
        n_steps_per_video <= n_steps_between_videos
    ) or not do_video, "len_video must be less than or equal to freq_video"

    # ================ Initialization ================

    # Set the seeds
    seed = try_get_seed(config)
    print(f"Using seed: {seed}")
    np.random.seed(seed)
    key_random = random.PRNGKey(seed)

    # Create the env
    env_name: str = config["env"]["name"]
    EnvClass = env_name_to_EnvClass[env_name]
    env = EnvClass(
        config=config["env"],
        n_agents_max=config["n_agents_max"],
        n_agents_initial=config["n_agents_initial"],
    )

    # Create the agent's species
    agent_species_name: str = config["agent"]["name"]
    AgentSpeciesClass = agent_name_to_AgentSpeciesClass[agent_species_name]
    agent_species = AgentSpeciesClass(
        config=config["agent"],
        n_agents_max=config["n_agents_max"],
        n_agents_initial=config["n_agents_initial"],
    )

    # Initialize loggers
    run_name = f"[{env_name}]_{datetime.datetime.now().strftime('%dth%mmo_%Hh%Mmin%Ss')}_seed{seed}"
    os.makedirs(f"logs/runs/{run_name}", exist_ok=True)
    print(f"\nStarting run {run_name}")
    if do_snakeviz:
        pr = cProfile.Profile()
        pr.enable()
    if do_wandb:
        run = wandb.init(
            name=run_name,
            config=config,
            **config["wandb_config"],
        )
    if do_tb:
        tb_writer = SummaryWriter(log_dir=f"tensorboard/{run_name}")

    # =============== Start simulation ===============
    print("Starting simulation...")
    key_random, subkey = random.split(key_random)
    (
        state_env,
        observations_agents,
        are_newborns_agents,
        indexes_parents_agents,
    ) = env.start(key_random=subkey)

    # ============== Simulation loop ===============
    print("Simulation started.")
    # Training loop
    for t in tqdm(range(n_timesteps), disable=not do_tqdm):

        # Save video frame
        if do_video:
            if t % n_steps_between_videos == 0:
                video_writer = VideoWriter(
                    # filename=f"logs/{run_name}/video_t{t}.mp4",
                    filename=f"logs/video_t{t}.mp4",
                    fps=20,
                )
            t_current_video = t - (t // n_steps_between_videos) * n_steps_between_videos
            if (t_current_video < n_steps_per_video) and (
                t_current_video % n_steps_between_frames == 0
            ):
                video_writer.add(env.get_RGB_map(state=state_env))
            if t_current_video == n_steps_per_video - 1:
                video_writer.close()

        # Agents step
        key_random, subkey = random.split(key_random)
        actions = agent_species.react(
            key_random=subkey,
            batch_observations=observations_agents,
            are_newborns=are_newborns_agents,
            indexes_parents=indexes_parents_agents,
        )

        # Env step
        key_random, subkey = random.split(key_random)
        (
            state_env,
            observations_agents,
            are_newborns_agents,
            indexes_parents_agents,
            done_env,
            info_env,
        ) = env.step(
            key_random=subkey,
            state=state_env,
            actions=actions,
        )
        if done_env:
            print("Environment done.")
            break

    # Finish the WandB run.
    if do_wandb:
        run.finish()
    if do_tb:
        tb_writer.close()
    if do_snakeviz:
        pr.disable()
        pr.dump_stats("logs/profile_stats.prof")
        print("Profile stats dumped to logs/profile_stats.prof")


if __name__ == "__main__":
    main()
